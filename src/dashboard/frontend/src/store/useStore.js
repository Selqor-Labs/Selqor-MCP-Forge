import { create } from 'zustand';
import { loadString, saveString, STORAGE_KEYS } from '../utils/persist';

let toastId = 0;

const useStore = create((set, get) => ({
  // Theme — persisted via utils/persist so every consumer uses the same key.
  theme: loadString(STORAGE_KEYS.theme, 'light'),
  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark';
    saveString(STORAGE_KEYS.theme, next);
    set({ theme: next });
  },

  // Sidebar
  sidebarOpen: false,
  sidebarHovered: false,
  setSidebarHovered: (val) => set({ sidebarHovered: val }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  closeSidebar: () => set({ sidebarOpen: false }),

  // Loading overlay
  loading: { visible: false, message: '' },
  showLoading: (message = 'Loading...') => set({ loading: { visible: true, message } }),
  hideLoading: () => set({ loading: { visible: false, message: '' } }),

  // Toasts
  toasts: [],
  toast: (message, type = '', duration = 4000) => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts, { id, message, type, duration }] }));
  },
  removeToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  // Integrations
  integrations: [],
  selectedIntegrationId: null,
  integrationStep: 1,
  completedSteps: [],

  // Runs
  runs: [],
  selectedRunId: null,
  activeRunJob: null,

  // Tooling
  tooling: null,
  toolingDraft: [],
  selectedToolIndex: null,

  // Auth
  auth: null,

  // Deployments
  deployments: [],

  // Versions
  versions: [],

  // Dashboard capability metadata
  authConfig: null,
}));

export default useStore;
