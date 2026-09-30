# Frontend

React + Tailwind UI for InvoiceAgent: batch setup, the analyst review queue, the invoice
detail view (escalation brief, evidence, analyst review), and the AP manager dashboard.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to the FastAPI server on :8000
npm run build      # type-check and production build to dist/
```

Set `VITE_API_BASE` to point a production build at a different API origin (default `/api`).
