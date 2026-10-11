import { create } from 'zustand';
import {
    apiDetail, createConnection, deleteConnection, listConnections, listConnectors, testConnection,
} from '../api/connectors';
import type { Connection, ConnectionCreate, ConnectionTest, ConnectorInfo } from '../api/connectors';

interface ConnectorState {
    connectors: ConnectorInfo[];
    connections: Connection[];
    loaded: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    add: (body: ConnectionCreate) => Promise<Connection>;
    remove: (id: string) => Promise<void>;
    test: (id: string) => Promise<ConnectionTest>;
}

/** The connector catalogue and this installation's connections, shared by the palette, inspector and Connections page. */
export const useConnectorStore = create<ConnectorState>((set, get) => ({
    connectors: [],
    connections: [],
    loaded: false,
    error: null,

    refresh: async () => {
        try {
            const [connectors, connections] = await Promise.all([listConnectors(), listConnections()]);
            set({ connectors, connections, loaded: true, error: null });
        } catch (error) {
            set({ loaded: true, error: apiDetail(error) });
        }
    },

    add: async (body) => {
        const connection = await createConnection(body);
        set({ connections: [...get().connections, connection] });
        return connection;
    },

    remove: async (id) => {
        await deleteConnection(id);
        set({ connections: get().connections.filter((connection) => connection.id !== id) });
    },

    test: async (id) => {
        const result = await testConnection(id);
        await get().refresh();
        return result;
    },
}));
