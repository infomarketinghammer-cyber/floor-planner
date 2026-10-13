import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client.ts'
import type { LengthUnit, ProjectMaterial, Room, RoomsState } from '../../api/types.ts'

const MAX_HISTORY = 50

export interface HistoryEntry {
  rooms: Room[]
  planUnit: { unit: LengthUnit | null; confirmed: boolean } // undoing a unit change restores it too
  defaultMaterial: ProjectMaterial // and so does undoing a change to the project's tile defaults
  label: string // e.g. "Delete Kitchen", shown on the undo button
}

function snapshot(state: RoomsState, label: string): HistoryEntry {
  return {
    // Keep only stored fields; issues and effective settings are recomputed by the server.
    rooms: state.rooms.map(
      ({ issues: _i, effective: _e, exclusion_area_mm2: _x, usable_area_mm2: _u, ...room }) => room,
    ),
    defaultMaterial: state.default_material,
    planUnit: { unit: state.plan_unit.confirmed ? state.plan_unit.unit : null, confirmed: state.plan_unit.confirmed },
    label,
  }
}

/**
 * Room review state (PRD 4.3). Every change is saved on the server, which returns the full
 * list with issues. Undo/redo put back earlier snapshots via a version-checked restore, so a
 * change made in another tab is never silently overwritten.
 */
export type RoomsReview = ReturnType<typeof useRoomsReview>

export function useRoomsReview(projectId: string, externalVersion: number, onSaved: () => void) {
  const [state, setState] = useState<RoomsState | null>(null)
  const [past, setPast] = useState<HistoryEntry[]>([])
  const [future, setFuture] = useState<HistoryEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const reload = useCallback(
    async (message = '') => {
      try {
        setState(await api.rooms.list(projectId))
        setPast([])
        setFuture([])
        setError(message)
      } catch (err) {
        setError((err as Error).message)
      }
    },
    [projectId],
  )

  // Initial load, and whenever rooms changed outside this section (e.g. extraction ran).
  useEffect(() => {
    let cancelled = false
    api.rooms
      .list(projectId)
      .then((next) => {
        if (cancelled) return
        setState(next)
        setPast([])
        setFuture([])
        setError('')
      })
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [projectId, externalVersion])

  const handleFailure = useCallback(
    async (err: unknown) => {
      if (err instanceof ApiError && err.status === 409) {
        await reload(`${err.message} Undo history was cleared.`)
      } else {
        setError((err as Error).message)
      }
    },
    [reload],
  )

  /** Run a change; on success the previous list becomes an undo step. Returns false on failure. */
  const mutate = useCallback(
    async (label: string, change: () => Promise<RoomsState>, options: { rethrow?: boolean } = {}): Promise<boolean> => {
      const before = stateRef.current
      setBusy(true)
      setError('')
      try {
        const next = await change()
        setState(next)
        if (before) {
          setPast((p) => [...p.slice(-(MAX_HISTORY - 1)), snapshot(before, label)])
          setFuture([])
        }
        onSaved()
        return true
      } catch (err) {
        if (options.rethrow && !(err instanceof ApiError && err.status === 409)) throw err
        await handleFailure(err)
        return false
      } finally {
        setBusy(false)
      }
    },
    [handleFailure, onSaved],
  )

  const travel = useCallback(
    async (direction: 'undo' | 'redo') => {
      const current = stateRef.current
      const stack = direction === 'undo' ? past : future
      const target = stack.at(-1)
      if (!current || !target || busy) return
      setBusy(true)
      setError('')
      try {
        const next = await api.rooms.restore(
          projectId,
          current.version,
          target.rooms,
          target.planUnit,
          target.defaultMaterial,
        )
        setState(next)
        const entry = snapshot(current, target.label)
        if (direction === 'undo') {
          setPast((p) => p.slice(0, -1))
          setFuture((f) => [...f, entry])
        } else {
          setFuture((f) => f.slice(0, -1))
          setPast((p) => [...p, entry])
        }
        onSaved()
      } catch (err) {
        await handleFailure(err)
      } finally {
        setBusy(false)
      }
    },
    [busy, future, handleFailure, onSaved, past, projectId],
  )

  /** Show a new state from a change that isn't an undo step (e.g. cost settings). */
  const replaceState = useCallback(
    (next: RoomsState) => {
      setState(next)
      onSaved()
    },
    [onSaved],
  )

  return {
    state,
    busy,
    error,
    setError,
    mutate,
    replaceState,
    undo: () => travel('undo'),
    redo: () => travel('redo'),
    undoLabel: past.at(-1)?.label ?? null,
    redoLabel: future.at(-1)?.label ?? null,
  }
}
