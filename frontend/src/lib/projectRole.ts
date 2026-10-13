import { createContext, use } from 'react'
import type { ProjectRole } from '../api/types.ts'

/** The viewer's role on the open project (PRD 4.18), for showing only what they can do. The
 * server enforces the same rules on every call. */
export const ProjectRoleContext = createContext<ProjectRole>('owner')

export function useProjectRole() {
  const role = use(ProjectRoleContext)
  return {
    role,
    canEdit: role !== 'homeowner',
    canSeeCosts: role === 'owner' || role === 'contractor',
    canManage: role === 'owner',
  }
}
