# MUVO

MUVO is a full-stack music playlist generator developed specifically to support the Radio Blaj team in preparing clean, structured, and customizable music playlists more efficiently.

The application retrieves popular tracks for a selected country, filters unwanted content, allows users to preview songs, build their own playlist, and generate a downloadable ZIP archive.

The main goal of MUVO is to reduce the amount of manual work involved in music selection and playlist preparation for Radio Blaj, while keeping the process fast, organized, and easy to use.

## Preview

<img width="1600" height="747" alt="muvo" src="https://github.com/user-attachments/assets/0bac25db-89d1-4ac9-b7dc-ec5c03da9c80" />


## Features

- Country-based Top 200 music charts
- Global chart support
- Explicit-content filtering
- Custom artist and genre filtering
- On-demand audio previews
- Personal playlist creation
- Search and filter functionality
- Playlist history
- Download selected tracks as a ZIP archive
- Responsive web interface
- Separate frontend and backend deployment
- Workflow designed around the practical needs of the Radio Blaj team

## Tech Stack

### Frontend

- React
- TypeScript
- Vite
- HTML
- CSS

### Backend

- Python
- REST API
- yt-dlp
- FFmpeg
- Requests
- BeautifulSoup

### External Services

- Spotify API
- Kworb music charts
- Render
- Vercel

## How It Works

MUVO follows a simple workflow:

1. The user selects a country or the global chart.
2. The backend retrieves current chart data.
3. Tracks are validated and filtered.
4. The resulting clean playlist is sent to the frontend.
5. Users can preview individual tracks.
6. Tracks can be added or removed from a personal playlist.
7. The selected playlist can be downloaded as a ZIP archive.

This workflow was designed to make the music preparation process for Radio Blaj faster and easier, especially when preparing larger playlists.

## Architecture

The project is split into two main components:

MUVO
│
├── assets/
│   └── muvo-preview.png
│
├── frontend/
│   ├── React
│   ├── TypeScript
│   └── Vite
│
├── server.py
├── country_top_200.py
├── descarca_saptamana.py
├── requirements.txt
└── README.md<img width="1600" height="747" alt="muvo" src="https://github.com/user-attachments/assets/3d8053b7-7da3-4ad6-a114-4420a0d796d6" />

The React frontend communicates with the Python backend through REST API endpoints.

The frontend is deployed separately from the backend:

React / Vite
     │
     │ REST API
     ▼
Python Backend
     │
     ├── Spotify API
     ├── Kworb
     └── Audio processing

## Running Locally

### 1. Clone the repository

git clone https://github.com/saranicusan88/MUVO.git
cd MUVO

### 2. Install Python dependencies

pip install -r requirements.txt

### 3. Configure environment variables

Create a `.env` file in the project root:

SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

Do not commit the `.env` file to GitHub.

### 4. Start the backend

python server.py

The backend will run locally on:

http://localhost:8765

### 5. Start the frontend

Open another terminal:

cd frontend
npm install
npm run dev

Then open the URL displayed by Vite in your browser.

## Deployment

The project can be deployed using:

- **Vercel** for the React frontend
- **Render** for the Python backend

The frontend uses the following environment variable to connect to the backend:

VITE_API_URL=https://your-backend-url.onrender.com

## Project Goals

MUVO was created specifically to help the Radio Blaj team simplify and automate part of the weekly music preparation workflow.

The project was built around a real-world use case rather than only as an academic exercise.

Its goals include:

- reducing repetitive manual work
- simplifying weekly playlist preparation
- providing cleaner and more organized song selection
- making large music lists easier to manage
- allowing quick preview and playlist customization
- creating a simple interface that can be used by members of the Radio Blaj team

From a software engineering perspective, the project also explores:

- REST API development
- frontend/backend separation
- asynchronous operations
- external API integration
- data filtering
- media processing
- state management
- deployment
- user interface design
- workflow automation


