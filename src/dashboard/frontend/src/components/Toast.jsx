import React from 'react';
import { useEffect, useRef } from 'react';
import { useSnackbar } from 'notistack';
import useStore from '../store/useStore';

/**
 * Bridge between Zustand toast store and notistack.
 * Watches for new toasts and forwards them to notistack's SnackbarProvider,
 * then removes from store so they don't fire twice.
 */
export default function Toast() {
  const toasts = useStore((s) => s.toasts);
  const removeToast = useStore((s) => s.removeToast);
  const { enqueueSnackbar } = useSnackbar();
  const displayed = useRef(new Set());

  useEffect(() => {
    toasts.forEach((t) => {
      if (displayed.current.has(t.id)) return;
      displayed.current.add(t.id);

      const variant = t.type === 'error' ? 'error'
        : t.type === 'success' ? 'success'
        : t.type === 'warning' ? 'warning'
        : 'default';

      enqueueSnackbar(t.message, {
        variant,
        autoHideDuration: t.duration || 4000,
      });

      removeToast(t.id);
    });
  }, [toasts, enqueueSnackbar, removeToast]);

  return null;
}
