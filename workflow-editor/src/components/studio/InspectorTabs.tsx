import type { LucideIcon } from 'lucide-react';

export interface InspectorTab {
    id: string;
    label: string;
    icon: LucideIcon;
    disabled?: boolean;
}

/** The inspector's sections, as a full-width segmented control. */
export const InspectorTabs = ({
    tabs,
    activeTab,
    onChange,
}: {
    tabs: InspectorTab[];
    activeTab: string;
    onChange: (tab: string) => void;
}) => (
    <div className="segmented is-wide is-dense" role="tablist" aria-label="Inspector sections">
        {tabs.map(({ id, label, disabled }) => (
            <button
                key={id}
                type="button"
                role="tab"
                disabled={disabled}
                aria-selected={activeTab === id}
                onClick={() => onChange(id)}
            >
                <span className="truncate">{label}</span>
            </button>
        ))}
    </div>
);
