"""Optional closure-only refinement of an existing, fully paid guess basis.

Candidates preserve the prepared model, file-known variables, weights,
forbidden guesses and synchronous propagation limit. Cost is minimized first;
at equal cost the heuristic prefers fewer propagation steps. Positive-cost
results carry no global optimality claim.
"""

from functools import lru_cache
import heapq
import random
import time

from core.lowerbounds import _BudgetExpired, _Deadline, _deduction_rules, _validated_model
from core.solverresult import basis_result, termination_result


def _target_depth(result):
    remaining = set(result["target_variables"])
    for record in result["determination_steps"]:
        remaining.difference_update(record["determined_vars"])
        if not remaining:
            return record["step"]
    return 0 if not remaining else None


class ClosureEngine:
    """Earliest-round propagation, equivalent to synchronous relation passes."""

    def __init__(self, model, max_steps, deadline=None):
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 0:
            raise ValueError("max_steps must be a nonnegative integer")
        self.deadline = deadline
        self.model = _validated_model(model)
        self.max_steps = max_steps
        self.variables = self.model["variables"]
        self.ids = {v: i for i, v in enumerate(self.variables)}
        self.known = frozenset(self.ids[v] for v in self.model["known_variables"])
        self.targets = frozenset(self.ids[v] for v in self.model["target_variables"])
        forbidden = {self.ids[v] for v in self.model["notguessed_variables"]}
        self.allowed = tuple(i for i in range(len(self.variables))
                             if i not in self.known and i not in forbidden)
        self.allowed_set = set(self.allowed)
        weights = self.model["target_weights"]
        self.weights = [weights.get(v, 1) for v in self.variables]
        self.premise_counts, self.heads, self.unconditional = [], [], []
        self.rules_by_premise = [[] for _ in self.variables]
        seen = set()
        for raw_premises, raw_head in _deduction_rules(self.model):
            self._check()
            premises = tuple(sorted(self.ids[v] for v in raw_premises))
            head = self.ids[raw_head]
            if (premises, head) in seen:
                continue
            seen.add((premises, head))
            rule = len(self.heads)
            self.heads.append(head)
            self.premise_counts.append(len(premises))
            if not premises:
                self.unconditional.append(head)
            for premise in premises:
                self.rules_by_premise[premise].append(rule)
        self.closure_calls = 0
        self.evaluate = lru_cache(maxsize=2048)(self._evaluate)

    def _check(self):
        if self.deadline is not None:
            self.deadline.check()

    def _evaluate(self, basis):
        self._check()
        self.closure_calls += 1
        reached = set(self.known) | set(basis)
        if self.targets <= reached:
            return True, len(self.targets), 0
        remaining = self.premise_counts.copy()
        agenda = [(0, variable) for variable in reached]
        if self.max_steps:
            agenda.extend((1, variable) for variable in self.unconditional if variable not in reached)
        heapq.heapify(agenda)
        processed, target_round = set(), 0
        while agenda:
            self._check()
            depth, variable = heapq.heappop(agenda)
            if variable in processed:
                continue
            processed.add(variable)
            reached.add(variable)
            if variable in self.targets:
                target_round = max(target_round, depth)
                if self.targets <= reached:
                    return True, len(self.targets), target_round
            if depth >= self.max_steps:
                continue
            for rule in self.rules_by_premise[variable]:
                self._check()
                remaining[rule] -= 1
                head = self.heads[rule]
                if remaining[rule] == 0 and head not in processed:
                    heapq.heappush(agenda, (depth + 1, head))
        return self.targets <= reached, len(self.targets & reached), target_round

    def assess(self, basis):
        self._check()
        key = tuple(sorted(set(basis)))
        if any(type(i) is not int or i < 0 or i >= len(self.variables) for i in key):
            raise ValueError("Closure basis contains an invalid variable index")
        return self.evaluate(key)

    def cost(self, basis):
        return sum(self.weights[i] for i in set(basis) - self.known)


def refine_basis(data, seed_basis, *, max_steps, time_limit=-1, budget=None,
                 random_seed=0, max_trials=100):
    """Refine a feasible seed and retain the validated incumbent on timeout.

    The optional shared ``budget.remaining()`` is combined with ``time_limit``.
    ``max_trials`` and ``random_seed`` give reproducible trial prefixes; a wall
    limit can truncate that prefix. Seed/final result validation may finish
    after the cooperative deadline, matching native solver result validation.
    """
    started = time.monotonic()
    deadline = _Deadline(time_limit, budget)
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 0:
        raise ValueError("max_steps must be a nonnegative integer")
    if isinstance(random_seed, bool) or not isinstance(random_seed, int):
        raise ValueError("random_seed must be an integer")
    if max_trials is not None and (isinstance(max_trials, bool)
            or not isinstance(max_trials, int) or max_trials < 0):
        raise ValueError("max_trials must be a nonnegative integer or None")
    if max_trials is None and deadline.remaining() == -1:
        raise ValueError("An unlimited trial count requires a finite time budget")
    if not isinstance(seed_basis, (list, tuple)) or any(not isinstance(v, str) for v in seed_basis):
        raise ValueError("seed_basis must contain variable IDs")
    model = _validated_model(data)
    variables = model["variables"]
    known, forbidden = set(model["known_variables"]), set(model["notguessed_variables"])
    supplied_seed = set(seed_basis)
    if not supplied_seed <= set(variables):
        raise ValueError("Unknown seed variable")
    paid_seed = supplied_seed - known
    if paid_seed & forbidden:
        raise ValueError("Forbidden seed guess")
    seed = [v for v in variables if v in paid_seed]
    seed_result = basis_result(model, seed, max_steps=max_steps)
    if seed_result["status"] != "sat":
        raise ValueError("Seed does not cover targets at the fixed propagation depth")
    seed_depth = _target_depth(seed_result)
    best_cost, best_depth = seed_result["cost"], seed_depth
    best_names = list(seed)
    engine = None
    trials = incomplete_trials = 0
    pool_list, history = [], []
    timed_out = False
    rng = random.Random(random_seed)

    try:
        deadline.check()
        if best_cost != 0 or best_depth != 0:
            engine = ClosureEngine(model, max_steps, deadline)
            best = {engine.ids[v] for v in seed}
            if engine.assess(best) != (True, len(engine.targets), seed_depth):
                raise RuntimeError("Refinement engine and core seed validation disagree")
            walk = set(best)
            pool = {tuple(sorted(best))}
            pool_list = [tuple(sorted(best))]

            while max_trials is None or trials < max_trials:
                deadline.check()
                if trials % 5 == 0:
                    candidate = set(engine.allowed)
                else:
                    if trials % 5 == 1:
                        walk = set(pool_list[rng.randrange(len(pool_list))])
                    outside = sorted(engine.allowed_set - walk)
                    candidate = walk | set(rng.sample(outside, min(len(outside), 1 + trials % 4)))
                order = sorted(candidate)
                rng.shuffle(order)
                if trials % 3:
                    order.sort(key=lambda variable: engine.weights[variable], reverse=True)
                trials += 1
                try:
                    for variable in order:
                        deadline.check()
                        without = candidate - {variable}
                        if engine.assess(without)[0]:
                            candidate = without
                    feasible, _, depth = engine.assess(candidate)
                except _BudgetExpired:
                    incomplete_trials += 1
                    raise
                if not feasible:
                    raise RuntimeError("Monotone basis refinement lost target coverage")
                cost = engine.cost(candidate)
                if cost <= best_cost:
                    walk = set(candidate)
                    fingerprint = tuple(sorted(candidate))
                    if fingerprint not in pool and len(pool_list) < 256:
                        pool.add(fingerprint)
                        pool_list.append(fingerprint)
                    if (cost, depth) < (best_cost, best_depth):
                        best_cost, best_depth = cost, depth
                        best_names = [engine.variables[i] for i in sorted(candidate)]
                        if len(history) < 256:
                            history.append({"trial": trials, "cost": cost,
                                            "propagation_steps": depth,
                                            "elapsed_seconds": time.monotonic() - started})
                        pool_list = [value for value in pool_list if engine.cost(value) <= cost]
                        pool = set(pool_list)
                        if fingerprint not in pool:
                            if len(pool_list) >= 256:
                                pool.remove(pool_list.pop(0))
                            pool.add(fingerprint)
                            pool_list.append(fingerprint)
                if best_cost == 0 and best_depth == 0:
                    break
    except _BudgetExpired:
        timed_out = True

    result = basis_result(model, best_names, max_steps=max_steps, optimal=best_cost == 0)
    if result["status"] != "sat" or result["cost"] != best_cost or _target_depth(result) != best_depth:
        raise RuntimeError("Refined basis failed independent core validation")
    result.update({
        "seed_basis": seed, "supplied_seed_basis": list(dict.fromkeys(seed_basis)),
        "seed_cost": seed_result["cost"], "seed_propagation_steps": seed_depth,
        "seed_deduction_rounds": seed_depth, "propagation_steps": best_depth,
        "deduction_rounds": best_depth, "max_steps": max_steps,
        "improved": best_cost < seed_result["cost"],
        "refinement_improved": (best_cost, best_depth) < (seed_result["cost"], seed_depth),
        "improvement_delta": seed_result["cost"] - best_cost,
        "refinement_method": "randomized_basis_exchange",
        "random_seed": random_seed, "max_trials": max_trials, "trials": trials,
        "incomplete_trials": incomplete_trials,
        "closure_evaluations": engine.closure_calls if engine else 0,
        "closure_cache": engine.evaluate.cache_info()._asdict() if engine else {},
        "unique_best_or_equal_bases": len(pool_list) if pool_list else 1,
        "history": history, "time_limit": time_limit,
        "elapsed_seconds": time.monotonic() - started,
        "proof_scope": "feasible_basis_only_no_positive_cost_optimality_claim",
    })
    reason = "optimal" if result["optimal"] else "time_limit" if timed_out else "trial_limit"
    return termination_result(result, reason)
