# TravelMind AI - Multi-Agent Travel Booking System ✈️🌍

TravelMind AI is an intelligent, multi-agent conversational travel booking system designed to help users plan and book flights and hotels seamlessly. It leverages an Agent-to-Agent (A2A) communication architecture to distribute tasks among specialized sub-agents. 

## Features 🚀

- **Multi-Agent Orchestration**: Utilizes a central Orchestrator agent to classify user intents and route requests to specialized sub-agents (Flight Agent, Hotel Agent).
- **Conversational Interface**: A dynamic, interactive chat UI built with Streamlit, enabling natural language travel planning.
- **Agent-to-Agent (A2A) Communication**: Agents communicate via JSON-RPC, ensuring a robust, stateless architecture for task delegation.
- **Model Context Protocol (MCP)**: Implements MCP for decoupled, secure API data fetching and tool execution.
- **Stateful Conversations**: Uses LangGraph and SQLite to maintain conversation memory and handle sequential slot-filling (e.g., ensuring travel dates and passenger counts are collected before booking).
- **Booking Management**: Confirmed bookings (flights and hotels) are tracked and displayed persistently on the frontend.

## Tech Stack 🛠️

- **LLM & Agent Framework**: [LangChain](https://python.langchain.com/), [LangGraph](https://python.langchain.com/docs/langgraph), [Cerebras Llama](https://cerebras.ai/)
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/), Uvicorn
- **Frontend**: [Streamlit](https://streamlit.io/)
- **Database**: SQLite, aiosqlite (for async DB operations and LangGraph checkpoints)
- **Integrations**: [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)

## Project Structure 📁

```text
Travel-Booking-Agent
├── README.md
├── requirements.txt
├── streamlit_app.py
├── app/
│   ├── a2a/
│   │   ├── client/
│   │   │   └── wrapper.py
│   │   ├── server/
│   │   │   ├── executor.py
│   │   │   └── router.py
│   │   └── schemas.py
│   ├── agents/
│   │   ├── base/
│   │   │   └── state.py
│   │   ├── flight/
│   │   │   ├── agent.json
│   │   │   ├── constants.py
│   │   │   ├── graph.py
│   │   │   ├── main.py
│   │   │   ├── nodes.py
│   │   │   └── state.py
│   │   ├── hotel/
│   │   │   ├── agent.json
│   │   │   ├── constants.py
│   │   │   ├── graph.py
│   │   │   ├── main.py
│   │   │   ├── nodes.py
│   │   │   └── state.py
│   │   └── orchestrator/
│   │       ├── constants.py
│   │       ├── graph.py
│   │       ├── main.py
│   │       ├── nodes.py
│   │       ├── prompts.py
│   │       ├── registry.py
│   │       └── state.py
│   ├── common/
│   │   └── registry.py
│   ├── core/
│   │   ├── checkpointer.py
│   │   ├── config.py
│   │   └── llm.py
│   ├── db/
│   │   └── schema.sql
│   ├── guardrails/
│   │   ├── input_validator.py
│   │   ├── prompts.py
│   │   └── types.py
│   └── services/
│       ├── flight_service.py
│       ├── hotel_service.py
│       ├── mcp_server.py
│       └── mock_data.json
├── interface/
│   └── app.py
└── tests/
    ├── test_flight_agent.py
    ├── test_hotel_agent.py
    └── test_orchestrator.py
```

## Getting Started 💻

### Prerequisites

- Python 3.9+
- A Cerebras API key (configured via environment variables)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/PSriSaiYagnik/Travel-Booking-Agent.git
   cd Travel-Booking-Agent
   ```

2. **Set up a virtual environment:**
   ```bash
   python -m venv env
   source env/bin/activate  # On Windows use: env\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   Create a `.env` file in the root directory and add necessary keys such as your Cerebras API key:
   ```env
   CEREBRAS_API_KEY=your_api_key_here
   ```

### Running the Application

1. **Start the Backend Orchestrator (FastAPI):**
   *(Typically handled by a script or uvicorn command. Example:)*
   ```bash
   uvicorn app.agents.orchestrator.main:app --reload --port 8000
   ```

2. **Start the Frontend UI (Streamlit):**
   In a separate terminal:
   ```bash
   streamlit run streamlit_app.py
   ```

Open your browser to `http://localhost:8501` to start chatting with TravelMind AI!
