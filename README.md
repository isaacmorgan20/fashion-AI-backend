# ThreadOS AI Agent Backend

FastAPI backend for the ThreadOS AI Customer Service & Commerce Agent.

## Features

- **AI-Powered Conversations**: Uses Google Gemini to understand customer intent and respond with real product/business data
- **Multi-Channel Support**: Handles conversations from WhatsApp, Instagram, Facebook, and Website
- **Product Integration**: Accesses real product catalog from Firestore for accurate responses
- **Order Assistance**: Helps customers with product discovery and order placement
- **Human Handoff**: Automatically detects when human intervention is needed
- **Firebase Integration**: Uses Firebase Admin SDK for authentication and data access
- **Context Awareness**: Maintains conversation history for coherent responses

## Architecture

```
fashion-AI/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app entry point
│   ├── config.py        # Configuration management
│   ├── firebase.py      # Firebase Admin SDK initialization
│   ├── models.py        # Pydantic models
│   ├── agent.py         # ThreadOS AI Agent logic
│   └── routes.py        # API endpoints
├── .env                 # Environment variables (not committed)
├── .env.example         # Example environment variables
├── pyproject.toml       # Python dependencies
└── README.md
```

## Setup

1. **Install dependencies**:
   ```bash
   pip install -e .
   ```

2. **Configure environment variables** (copy `.env.example` to `.env`):
   ```bash
   cp .env.example .env
   ```
   Fill in:
   - Firebase service account credentials
   - Google AI (Gemini) API key

3. **Run the server**:
   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. **Access API docs**: http://localhost:8000/docs

## API Endpoints

### Conversations
- `GET /api/v1/conversations` - List conversations (with filters)
- `GET /api/v1/conversations/{id}` - Get conversation with messages
- `POST /api/v1/conversations` - Create new conversation
- `PATCH /api/v1/conversations/{id}` - Update conversation (mode, status)
- `POST /api/v1/conversations/{id}/messages` - Send message

### AI Chat
- `POST /api/v1/chat` - Get AI response for customer message

### Products
- `GET /api/v1/products` - List all products
- `GET /api/v1/products/{id}` - Get single product
- `POST /api/v1/products` - Create product
- `PATCH /api/v1/products/{id}` - Update product
- `DELETE /api/v1/products/{id}` - Delete product

### Business Info
- `GET /api/v1/business/info` - Get business configuration for AI

## AI Agent Capabilities

The ThreadOS AI Agent (`app/agent.py`) can:

1. **Product Inquiries**: Answer questions about availability, price, sizes, colors
2. **Order Assistance**: Help customers place orders using real product data
3. **Policy Questions**: Delivery, returns, payments
4. **Context Awareness**: Uses last 6 messages for context
5. **Handoff Detection**: Transfers to human when:
   - Customer explicitly requests human
   - Low confidence in response
   - Complex issues (complaints, refunds)

## Frontend Integration

The React frontend (`fashion-code/`) connects via:
- `src/service/api.js` - API client with Firebase auth
- `src/hooks/useConversations.js` - Conversation state management
- `src/hooks/useAIChat.js` - AI chat integration
- `src/Pages/Inbox.jsx` - Updated to use API (no more mock data)

## Environment Variables

| Variable | Description |
|----------|-------------|
| `FIREBASE_PROJECT_ID` | Firebase project ID |
| `FIREBASE_PRIVATE_KEY` | Service account private key |
| `FIREBASE_CLIENT_EMAIL` | Service account email |
| `GOOGLE_AI_API_KEY` | Gemini API key from Google AI Studio |
| `APP_PORT` | Backend port (default: 8000) |
| `FRONTEND_URL` | Frontend URL for CORS |
| `AI_MODEL` | Gemini model (default: gemini-1.5-flash) |
| `AI_TEMPERATURE` | Response creativity (0.0-1.0) |
| `AI_MAX_TOKENS` | Max response length |

## Security

- All API endpoints require Firebase ID token authentication
- AI/API secrets kept on backend only
- Firebase Admin SDK for server-side operations
- CORS configured for frontend origin only

## Development

```bash
# Backend
cd fashion-AI
python -m uvicorn app.main:app --reload

# Frontend (separate terminal)
cd fashion-code
npm run dev
```

## Production Deployment

1. Set `APP_ENV=production`
2. Use proper Firebase service account
3. Configure Gemini API key
4. Deploy FastAPI with Gunicorn/Uvicorn workers
5. Set up HTTPS and proper CORS origins