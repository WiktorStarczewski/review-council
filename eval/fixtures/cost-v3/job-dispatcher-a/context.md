# Settled dispatcher decisions

The subsystem is synchronous and deterministic. Numeric time values come from callers;
no worker waits for a real clock. The storage object is the transaction boundary for
state transitions and event production. Real databases, networking and distributed
coordination are outside the current package's intended scope.

Handlers own their input copies. Public status responses own their output data.
Diagnostics are intended for people and carry no exact text compatibility promise.
The recording sink is an integration contract example, with stable identity replay
and explicit receipts. A later review still needs to check new changes against the
actual source and callers rather than treating this summary as a prior approval.
