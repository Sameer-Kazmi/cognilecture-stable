# CogniLecture — Frontend

CogniLecture is an AI-powered lecture learning application that converts
educational videos into structured study materials through an interactive
web interface.

The frontend is built with React and Vite and communicates with the
FastAPI backend.

## Features

- Submit lecture video links for processing.
- View generated study notes and diagrams.
- Practice quizzes at different difficulty levels.
- Ask follow-up questions about lecture content.
- View backend and system telemetry.

## Requirements

- Node.js and npm
- The CogniLecture backend running
- Ollama running with the configured language model

## Setup

Install dependencies:

    npm install

Start the development server:

    npm run dev

Build the production frontend:

    npm run build

## Backend Configuration

The API base URL is configured in `src/api/client.js`.

To customize it, set `VITE_API_BASE_URL` in a frontend `.env` file.
See `.env.example` for the configuration format.

## Project Structure

- `src/components/` — Reusable UI components
- `src/pages/` — Application pages
- `src/api/` — API client configuration
- `src/hooks/` — Reusable React hooks
- `scripts/` — Development and screenshot utilities
