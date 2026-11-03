**LiveRecall server correctness walkthrough**

The current checkpoint implements revision state and recovery. The supplied source and public measurement tools are unchanged. The browser is still the starter, and semantic overload handling is the next server phase.

**Follow one caption through the server.**

1. handler reads a hello and validates its role/session. For a client, client_resume validates the cursor and requested history window before session state can change. One session and one simultaneous source are supported.
2. handle_source reads a caption. Caption.from_message validates the required fields and serializes the accepted fields once. Booleans cannot stand in for integer IDs; timestamps must be finite. Extra source fields and SOURCE_DONE do not change state.
3. SessionState.accept rejects equal/older revisions and updates to final captions. A provisional revision replaces active[segment]. A final removes that active entry and enters the final history. The number of revisions is not fixed.
4. The accepted immutable Caption is enqueued for each client. The source never waits for every client to finish sending.
5. Each ClientSender is the only task that sends application messages on its connection. It drains that client's pending queue in order.

**Follow a reconnect.** The hello cursor describes the newest finalized state already held by the client. For example, after final segment 38 revision 3, recovery may return recent finals 39 onward; it must not replay final 38. SessionState.snapshot filters by the requested source-time window and cursor, and orders finals by segment/revision. HISTORY contains finals only. Current active captions follow as ordinary CAPTION_UPDATE messages.

The snapshot and client registration run together without an await. A source update therefore either precedes the snapshot or is placed in the new client's live queue. The sender emits all history first, then the active snapshot, then queued live traffic. For unusually large histories it emits multiple ordered HISTORY frames, each at most 1 MiB; the supplied clients already handle these messages. An immediate reconnect can repeat a provisional snapshot because the protocol only acknowledges finals. The browser must ignore equal or stale provisional revisions.

**State and memory have explicit limits.**

| State | Current bound | Behavior |
|---|---|---|
| Final history | 60 seconds from receipt, at most 32,768 captions and 32 MiB of serialized caption bytes | Prune by age and capacity; recovery additionally filters source_ts by the requested 0–60-second window. Extreme rates can shorten retention at the hard caps. |
| Active captions | 128 segments and 4 MiB of serialized caption bytes | Keep the latest revision; reject a source that exceeds this capacity rather than allow growth without a bound. |
| Pending live queue per client | 256 captions and 2 MiB of serialized bytes | Interim policy closes an overflowing client with code 1013; it must reconnect and recover. |
| Initial recovery snapshot | References to bounded final/active state | Shared payloads are not eagerly copied, but a blocked sender can retain old payloads after global pruning. The pending queue's 2 MiB limit is not a total per-client memory claim. |
| Outgoing history frame | At most 1 MiB, measured as UTF-8 bytes | Split a large history into ordered frames rather than silently omit retained finals. |

The highest first-seen segment ID remains as one integer after old finals are pruned. A new arrival for an older segment that is no longer active is rejected, so expiry cannot allow old captions to reappear. An active older segment may still receive newer revisions. This uses the specified increasing first appearances of segment IDs.

**What this checkpoint does not establish.** FIFO overflow disconnect is a temporary correctness policy. The final design still needs to replace obsolete provisional work during actual overload, preserve fresh finals/latest active state, resume full updates afterward, and show the improvement in measurements. Fixed history capacities and transport buffering must be considered in those experiments. Passing startup compatibility alone does not establish any of this.

**The gate explanation takes about 10 minutes.** The student should trace one provisional-to-final update, explain why stale state cannot overwrite it, describe exactly what reconnect after final 38 returns, identify the no-await handoff, name each resource bound, and explain why dropping all provisional revisions would violate normal-operation coverage. Record the explanation in DESIGN_NOTES.md only after it happens.
