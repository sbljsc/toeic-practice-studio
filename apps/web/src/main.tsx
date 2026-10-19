import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './ui/App';
import { getTabId } from './domain/tab';
import './ui/styles.css';

// Establish the session tab identity before any API write can happen.
getTabId();

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
