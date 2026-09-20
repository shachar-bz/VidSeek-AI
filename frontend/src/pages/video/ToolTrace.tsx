import type { ToolCallTrace } from "../../api/types";

export function ToolTrace({ calls }: { calls: ToolCallTrace[] | null }) {
  if (!calls?.length) return null;
  return (
    <details className="tool-trace" open={calls.some((call) => call.finished_at === null)}>
      <summary>{calls.length} retrieval {calls.length === 1 ? "step" : "steps"}</summary>
      <ol>
        {calls.map((call) => {
          const active = call.finished_at === null;
          return (
            <li key={call.call_id} className={active ? "tool-trace__call tool-trace__call--active" : "tool-trace__call"}>
              <div className="tool-trace__heading">
                <code>{call.tool}</code>
                <span>{active ? "In progress…" : call.error ? "Failed" : "Complete"}</span>
              </div>
              <pre>{JSON.stringify(call.arguments, null, 2)}</pre>
              {call.error ? <p className="tool-trace__error">{call.error}</p> : null}
              {!call.error && call.summary ? <p>{call.summary}</p> : null}
              {!active && !call.error && !call.summary ? <p>No retrieval results were returned.</p> : null}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
