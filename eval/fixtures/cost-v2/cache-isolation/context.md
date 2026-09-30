# Settled operational decisions

This utility package is synchronous and in-process. Network services and durable storage are outside its present scope. Public docstrings and actual callers remain the behavioral contracts. Review history is advisory: a new change or interaction can invalidate a settled decision, and a concrete contradiction still needs a finding.

## Clock and capacity

Expiration uses numeric seconds from the injected clock, so tests can advance a controlled clock without waiting for real time. Exact-deadline expiry and eager cleanup of expired entries remain established behavior. Entry capacity is configured by the caller. These operational choices do not require persistence, background tasks or asynchronous eviction.

## Text presentation

The text presenter accepts labels and values that are already formatted by its caller. It returns plain text and has no dependency on locale services. Currency conversion, date formatting, grouping separators and precision policy belong to the caller. This boundary was chosen so the presenter can be used in scripts, tests and interactive programs with identical output.

## Presentation order

Row order follows the supplied list, including repeated labels. Sorting inside the presenter would replace a caller choice with an implicit policy. Callers that need alphabetical or chronological order prepare that order before presentation. The existing renderer therefore performs one ordered traversal and emits one line for each supplied row.

## Presentation output ownership

The renderer returns a string without writing to files, logs or the terminal. The caller chooses the output destination and any transport encoding. Empty input returns an empty string. Nonempty output has line breaks between rows and no additional trailing line break. Terminal printing may add its own final line break at the call site.

## Presentation markup

The returned string is plain text, with no interpretation of labels or values as markup. Applications that display it in HTML, a terminal protocol or another structured format own the escaping at that boundary. The renderer is deliberately independent of those presentation environments. A new markup consumer must preserve that ownership rather than changing all existing plain text callers.

