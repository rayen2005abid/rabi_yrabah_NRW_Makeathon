# Domain ownership rules

The application layer may call domain services. Domain services may depend on lower-level fact providers (`warehouse`, `inventory`, `events`, `core`) but the frontend and embedded adapter never call persistence directly.

`fifo` owns ordering, `fulfillment` owns box/quantity allocation, `slotting` owns equivalent-slot ranking, `safety` owns deterministic interlocks, `robot` owns semantic tasks/path/scheduling, and `embedded` owns command/telemetry transport. No AI/forecast result is allowed to bypass FIFO, drying, quantity arithmetic, occupancy, or safety.

Planning never decrements inventory. Simulation reads snapshots and stores only simulation artifacts. Actual quantity changes happen only at picking confirmation. Physical movement is finalized only through the embedded adapter ACK/telemetry path.
