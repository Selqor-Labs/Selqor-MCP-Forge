import React from 'react';
import Backdrop from '@mui/material/Backdrop';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import useStore from '../store/useStore';

export default function LoadingOverlay() {
  const loading = useStore((s) => s.loading);
  const theme = useStore((s) => s.theme);

  if (!loading.visible) return null;

  const dark = theme === 'dark';

  return (
    <Backdrop open sx={{ zIndex: (t) => t.zIndex.modal + 100 }}>
      <Paper
        elevation={6}
        sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', p: 4, borderRadius: 2 }}
      >
        <div className="loading-logo-motion" aria-hidden="true">
          <img className="loading-mark-part loading-part-one" src={dark ? '/assets/selqor-symbol-one-dark.svg' : '/assets/selqor-symbol-one-light.svg'} alt="" />
          <img className="loading-mark-part loading-part-two" src={dark ? '/assets/selqor-symbol-two-dark.svg' : '/assets/selqor-symbol-two-light.svg'} alt="" />
          <img className="loading-mark-part loading-part-three" src={dark ? '/assets/selqor-symbol-three-dark.svg' : '/assets/selqor-symbol-three-light.svg'} alt="" />
          <img className="loading-mark-part loading-part-four" src={dark ? '/assets/selqor-symbol-four-dark.svg' : '/assets/selqor-symbol-four-light.svg'} alt="" />
          <img className="loading-logo-mark" src={dark ? '/assets/selqor-mark-dark.svg' : '/assets/selqor-mark-light.svg'} alt="" />
        </div>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          {loading.message || 'Loading...'}
        </Typography>
      </Paper>
    </Backdrop>
  );
}
