
import { useState } from 'react';
import { X, Search, Check, Loader2 } from 'lucide-react';
import { useLibraryStore } from '../stores/libraryStore';

interface SwaggerImportModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export const SwaggerImportModal = ({ isOpen, onClose }: SwaggerImportModalProps) => {
    const { previewSwagger, importSwagger, isLoading } = useLibraryStore();
    const [url, setUrl] = useState('');
    const [step, setStep] = useState<'input' | 'preview'>('input');
    const [previewData, setPreviewData] = useState<any>(null);
    const [selectedEndpoints, setSelectedEndpoints] = useState<string[]>([]);
    const [error, setError] = useState<string | null>(null);

    const handlePreview = async () => {
        if (!url) return;
        setError(null);
        try {
            const data = await previewSwagger(url);
            setPreviewData(data);
            // Select all by default
            setSelectedEndpoints((data.endpoints ?? []).map((endpoint: any) => endpoint.operation_id));
            setStep('preview');
        } catch (err) {
            setError((err as Error).message);
        }
    };

    const handleImport = async () => {
        if (selectedEndpoints.length === 0) return;
        try {
            await importSwagger(url, selectedEndpoints);
            onClose();
            // Reset state
            setStep('input');
            setUrl('');
            setPreviewData(null);
        } catch (err) {
            setError((err as Error).message);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="sheet-backdrop !z-[110]" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
            <div className="sheet flex max-h-[80vh] w-[600px] max-w-full flex-col overflow-hidden" role="dialog" aria-modal="true" aria-label="Import tools from OpenAPI">
                {/* Header */}
                <div className="flex items-center justify-between gap-3 px-6 pb-2 pt-5">
                    <h2 className="title-2">Import tools from OpenAPI</h2>
                    <button onClick={onClose} className="btn btn-ghost btn-icon" aria-label="Close" title="Close">
                        <X size={15} />
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 flex-1 overflow-y-auto">
                    {error && (
                        <div className="mb-4 rounded-xl p-3 text-[12.5px]" style={{ background: 'var(--clay-wash)', color: 'var(--clay)' }}>
                            {error}
                        </div>
                    )}

                    {step === 'input' ? (
                        <div className="space-y-4">
                            <div>
                                <label className="field-label">Swagger / OpenAPI URL</label>
                                <input
                                    type="text"
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="https://api.example.com/openapi.json"
                                    className="input"
                                />
                                <p className="hint mt-1">Provide a URL to a valid JSON OpenAPI specification.</p>
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <h3 className="headline">Select Tools to Import</h3>
                                <div className="text-sm text-gray-500">
                                    {selectedEndpoints.length} selected
                                </div>
                            </div>

                            <div className="table-box max-h-[300px] overflow-y-auto">
                                {previewData?.endpoints.map((tool: any) => (
                                    <label key={tool.operation_id} className="flex items-start gap-3 p-3 border-b border-gray-100 last:border-0 hover:bg-gray-50 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={selectedEndpoints.includes(tool.operation_id)}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setSelectedEndpoints([...selectedEndpoints, tool.operation_id]);
                                                } else {
                                                    setSelectedEndpoints(selectedEndpoints.filter(id => id !== tool.operation_id));
                                                }
                                            }}
                                            className="mt-1 h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500"
                                        />
                                        <div>
                                            <div className="font-medium text-sm text-gray-900">{tool.name}</div>
                                            <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{tool.description}</div>
                                            <div className="mt-1 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-800 uppercase">
                                                {tool.method}
                                            </div>
                                        </div>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="flex justify-end gap-2 px-6 pb-5 pt-3" style={{ boxShadow: '0 -1px 0 var(--line)' }}>
                    {step === 'input' ? (
                        <>
                            <button onClick={onClose} className="btn">Cancel</button>
                            <button
                                onClick={handlePreview}
                                disabled={!url || isLoading}
                                className="btn btn-primary"
                            >
                                {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                                Preview
                            </button>
                        </>
                    ) : (
                        <>
                            <button onClick={() => setStep('input')} className="btn">Back</button>
                            <button
                                onClick={handleImport}
                                disabled={selectedEndpoints.length === 0 || isLoading}
                                className="btn btn-primary"
                            >
                                {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                                Import Selected
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};
