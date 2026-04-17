import React, { useRef, useEffect } from 'react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import useHotkey from '../utils/useHotkey';

export default function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title = 'Confirm',
  message = 'Are you sure?',
  confirmLabel = 'Confirm',
  confirmClass = 'btn-primary',
  cancelLabel = 'Cancel',
  loading = false,
}) {
  const isDestructive = confirmClass === 'btn-danger';
  const confirmRef = useRef(null);

  // Feature 7 polish: Enter fires the primary action, matching native
  // OS dialog behaviour. Escape is already handled by MUI via onClose.
  // For destructive actions we still require explicit click — hitting
  // Enter on a "Delete everything?" prompt is a foot-gun.
  useHotkey('Enter', () => {
    if (!loading && !isDestructive) onConfirm?.();
  }, { enabled: !!open, allowInInputs: true });

  // Auto-focus the confirm button when the dialog opens so keyboard
  // users don't have to tab into the action row.
  useEffect(() => {
    if (open && !isDestructive) {
      // Delay one tick so MUI has inserted the node into the DOM.
      const id = setTimeout(() => confirmRef.current?.focus(), 0);
      return () => clearTimeout(id);
    }
    return undefined;
  }, [open, isDestructive]);

  return (
    <Dialog open={!!open} onClose={loading ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText variant="body2">{message}</DialogContentText>
      </DialogContent>
      <DialogActions sx={{ px: 2.5, pb: 2 }}>
        <Button variant="text" size="small" onClick={onClose} disabled={loading}>{cancelLabel}</Button>
        <Button
          ref={confirmRef}
          variant="contained"
          size="small"
          color={isDestructive ? 'error' : 'primary'}
          onClick={onConfirm}
          disabled={loading}
        >
          {loading ? 'Working...' : confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
