import { createContext, useContext } from 'react';
import type { LibraryTab } from '../stores/uiStore';

export interface LibraryModalContextType {
    openLibraryModal: (tab?: LibraryTab) => void;
}

// Kept for components that open the Library by tab; it now navigates to the
// Library place in the sidebar rather than stacking a modal over the Studio.
export const LibraryModalContext = createContext<LibraryModalContextType>({
    openLibraryModal: () => { },
});

export const useLibraryModal = () => useContext(LibraryModalContext);
