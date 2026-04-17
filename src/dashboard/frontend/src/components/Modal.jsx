import React from 'react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import IconButton from '@mui/material/IconButton';
import CloseIcon from '@mui/icons-material/Close';

const sizeMap = { 'modal-sm': 'xs', 'modal-lg': 'md' };

export default function Modal({ open, onClose, title, children, className = '' }) {
  const maxWidth = sizeMap[className] || 'sm';

  return (
    <Dialog open={!!open} onClose={onClose} maxWidth={maxWidth} fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 1.5, px: 2.5 }}>
        {title}
        <IconButton size="small" onClick={onClose} sx={{ ml: 1 }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent sx={{ px: 2.5, pb: 2.5 }}>
        {children}
      </DialogContent>
    </Dialog>
  );
}
