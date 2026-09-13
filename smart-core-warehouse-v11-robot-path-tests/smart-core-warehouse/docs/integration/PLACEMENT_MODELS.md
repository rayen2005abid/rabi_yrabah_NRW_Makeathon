# Placement Decision Models

The Smart Core Warehouse chooses the best storage place with an explainable hybrid optimizer.

## Models Used

1. Weighted slot scoring
   - Minimizes physical travel cost.
   - Rewards accessibility.
   - Avoids poor rack balance.

2. Demand forecasting
   - Estimates future demand for the detected core type.
   - High-demand cores are placed where future retrieval is easier.

3. A* route planning
   - Computes the passage and transfer-lane path between robot position, source, and destination.
   - Adds real route distance to the placement score.

4. Reinforcement-learning assisted placement policy
   - Adds a policy-value signal from expected reward.
   - Reward favors short travel, high accessibility, balanced rack usage, and fast future retrieval.
   - The policy is used as a placement optimizer signal, not as a black-box replacement for safety rules.

## Final Decision

For each free slot, the system calculates:

```text
final_score =
  travel_weight * travel_cost
  + future_weight * future_retrieval_cost
  + congestion_weight * congestion
  + balance_weight * rack_balance
  - accessibility_weight * accessibility
  - rl_policy_weight * reinforcement_learning_policy_value
```

Lower score is better.

The Admin Panel shows the compared candidate slots, including travel, A* passage distance, RL policy value, rank, and selected destination.

