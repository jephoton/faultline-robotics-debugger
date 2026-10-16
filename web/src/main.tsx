import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { applyStoredTheme } from './lib/theme';
import './styles/index.css';

applyStoredTheme();

const root = document.getElementById('root');
if (!root) {
  throw new Error('Missing #root element');
}
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
