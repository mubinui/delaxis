import { ArrowDownToDot, ArrowUpFromDot } from 'lucide-react';
import type { WorkflowNodeData } from '../../types/workflow';

/**
 * Small in/out marks shown on a node once a run has captured its data.
 * Full payloads live in the inspector's Data tab.
 */
export function IoBadges({ data }: { data: WorkflowNodeData }) {
    if (!data.lastInput && !data.lastOutput) return null;
    return (
        <>
            {data.lastInput && (
                <span className="chip" title="Input captured — open the Data tab to inspect">
                    <ArrowDownToDot size={10} /> In
                </span>
            )}
            {data.lastOutput && (
                <span className="chip" title="Output captured — open the Data tab to inspect">
                    <ArrowUpFromDot size={10} /> Out
                </span>
            )}
        </>
    );
}
