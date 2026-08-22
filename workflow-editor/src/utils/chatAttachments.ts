/**
 * Attaching files to a chat message.
 *
 * The naive version of this names the file and tells the agent to go and
 * retrieve it. That only works if the workflow happens to have a retrieval tool
 * attached, and when it does not, a model asked about a file it cannot read
 * does not say so — it answers from the filename and invents the contents. A
 * confident invention attributed to a real document is worse than a refusal.
 *
 * So the passages are fetched here and travel with the question. Any workflow
 * can then answer from an attachment, whether or not it has tools, and when
 * retrieval finds nothing the message says the file could not be read rather
 * than leaving the model to guess.
 */

export interface UploadedFile {
    file: string;
    indexed: boolean;
    chunks?: number;
    error?: string | null;
}

export interface Passage {
    text: string;
    score: number;
    source: string;
}

/** Indexed per conversation, so one chat's uploads stay out of another's. */
export const collectionForSession = (sessionId: string): string => `chat-${sessionId}`;

/** How much attached text may accompany one message. */
export const CONTEXT_BUDGET = 6000;

export const uploadAttachments = async (
    baseUrl: string,
    collection: string,
    files: File[],
): Promise<UploadedFile[]> => {
    if (!files.length) return [];

    const body = new FormData();
    files.forEach((file) => body.append('files', file, file.name));

    // Content-Type is left unset deliberately: setting it by hand omits the
    // boundary the browser generates and the server rejects the body.
    const response = await fetch(
        `${baseUrl}/api/v1/rag/collections/${encodeURIComponent(collection)}/files`,
        { method: 'POST', body },
    );
    if (!response.ok) {
        throw new Error(`Upload failed (${response.status})`);
    }
    const result = await response.json();
    return (result.files ?? []) as UploadedFile[];
};

export const retrievePassages = async (
    baseUrl: string,
    collection: string,
    query: string,
    topK = 6,
): Promise<Passage[]> => {
    try {
        const response = await fetch(
            `${baseUrl}/api/v1/rag/collections/${encodeURIComponent(collection)}/query`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // A message with no words is still a request to look at the file.
                body: JSON.stringify({ query: query || 'summarise this document', top_k: topK }),
            },
        );
        if (!response.ok) return [];
        return ((await response.json()).results ?? []) as Passage[];
    } catch {
        return [];
    }
};

/** Build the message that is actually sent, given what was retrieved. */
export const composeMessage = (
    text: string,
    names: string[],
    passages: Passage[],
    budget = CONTEXT_BUDGET,
): string => {
    if (!names.length) return text;
    const listed = names.join(', ');

    if (!passages.length) {
        return `${text || 'I have attached a file.'}\n\n[Attached: ${listed}. The text could not `
            + 'be read, so answer only from what is already known and say the attachment could '
            + 'not be read.]';
    }

    // Budgeted: a long document would otherwise crowd out the conversation.
    let remaining = budget;
    const quoted: string[] = [];
    for (const passage of passages) {
        const body = String(passage.text ?? '');
        if (body.length > remaining) break;
        remaining -= body.length;
        quoted.push(`--- ${passage.source || 'attachment'} ---\n${body}`);
    }

    if (!quoted.length) {
        // Every passage was larger than the budget; send the head of the first
        // rather than claiming nothing could be read.
        quoted.push(
            `--- ${passages[0].source || 'attachment'} ---\n`
            + `${String(passages[0].text ?? '').slice(0, budget)}`,
        );
    }

    return `${text || 'Please read the attached file and summarise it.'}\n\n`
        + `[Attached: ${listed}. The relevant extracts follow. Answer from these, and say so `
        + 'if they do not contain the answer.]\n\n'
        + quoted.join('\n\n');
};

/** Upload, retrieve and compose in one step. Returns the message to send. */
export const attachAndCompose = async (
    baseUrl: string,
    sessionId: string,
    text: string,
    files: File[],
): Promise<{ message: string; uploaded: UploadedFile[] }> => {
    const collection = collectionForSession(sessionId);
    const uploaded = await uploadAttachments(baseUrl, collection, files);
    const indexed = uploaded.filter((item) => item.indexed).map((item) => item.file);
    if (!indexed.length) {
        return { message: composeMessage(text, uploaded.map((item) => item.file), []), uploaded };
    }
    const passages = await retrievePassages(baseUrl, collection, text);
    return { message: composeMessage(text, indexed, passages), uploaded };
};
