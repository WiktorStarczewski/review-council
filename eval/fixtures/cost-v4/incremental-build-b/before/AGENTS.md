# Incremental build contracts

This package provides deterministic in-process builds for tenant projects. A
project owns its source mapping, target DAG, compiler options, cache index, and
current manifest. A bundle's identity follows its recipe, source bytes, compiler
options, and dependency inputs. The compiler emits canonical bytes. Identical
bytes may share global content-addressed storage without sharing project heads.

Source and option changes advance the project input version; identical writes
are no-ops. Published outputs are current only while their inputs remain valid.
Plans freeze their inputs, and publication replaces the selected project head
only when its input version and prior manifest revision still match. A complete
manifest names available artifacts for every published target. Validation failure
preserves the head, cache index, and publication revision.

Builds expose begin, compile, and finish as separate synchronous caller steps.
Cancellation before publication is terminal. Active compiled artifacts remain
owned until publication, cancellation, or failure. Collection keeps current
manifests and active staging ownership; cache-only references are weak and may be
collected. A missing cached object is rebuilt. Public snapshots and supplied
source/option mappings do not share mutable ownership with the catalog.

These objects are a trusted coordinator library, not a network service or an
authentication layer. Project keys supplied to public project operations identify
the caller's authorized scope; returned build IDs are coordinator capabilities.
No filesystem, durable database, real thread, wall clock, or distributed lock is
required. Graphs reject cycles and undeclared dependencies. Diagnostics have no
exact-text compatibility promise. Use the actual consumers when judging changes
and review only this source tree.
