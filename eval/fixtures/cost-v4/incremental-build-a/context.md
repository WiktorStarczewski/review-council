# Settled build decisions

The compiler and catalog are deterministic synchronous objects. Build callers
may interleave the exposed begin, compile, finish, and cancellation steps.
Content-addressed bytes may be shared; project manifests and versioned inputs
remain separate. Collection is explicit and cache-only objects are weak.
Diagnostics have no exact text promise. Persistence, networking, and real
threads are outside this package's intended scope.
