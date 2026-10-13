// Runs the FastAPI backend (or its tests) with the backend venv's Python on any OS.
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'

const backendDir = path.resolve(import.meta.dirname, '..', 'backend')
const python = path.join(
  backendDir,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
if (!existsSync(python)) {
  console.error('Backend venv not found. See README "Setup" to create backend/.venv.')
  process.exit(1)
}

// watchfiles instead of `uvicorn --reload`: on Windows uvicorn's reloader restarts via
// CTRL_C_EVENT, which is never delivered when stdout is piped (as under concurrently),
// so reloads hang. watchfiles falls back to killing the process after a timeout.
const args =
  process.argv[2] === 'test'
    ? ['-m', 'pytest']
    : ['-m', 'watchfiles', '--filter', 'python', '--sigint-timeout', '3', 'devserver.run', 'app']

spawn(python, args, { cwd: backendDir, stdio: 'inherit' }).on('exit', (code) => process.exit(code ?? 0))
