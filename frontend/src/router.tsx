import { createBrowserRouter } from 'react-router'
import { PublicOrApp, RedirectHome, RequireAuth } from './auth/RequireAuth.tsx'
import { AppLayout } from './components/AppLayout.tsx'
import { AccountPage } from './pages/AccountPage.tsx'
import { AdminPage } from './pages/admin/AdminPage.tsx'
import { HomePage } from './pages/HomePage.tsx'
import { LandingPage } from './pages/LandingPage.tsx'
import { LoginPage } from './pages/LoginPage.tsx'
import { PrivacyPage } from './pages/PrivacyPage.tsx'
import { SharedPage } from './pages/SharedPage.tsx'
import { TeamPage } from './pages/TeamPage.tsx'
import { ProjectPage } from './pages/ProjectPage.tsx'
import { RegisterPage } from './pages/RegisterPage.tsx'
import { TilesPage } from './pages/TilesPage.tsx'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <PublicOrApp publicPage={<LandingPage />} app={<AppLayout />} />,
    children: [{ index: true, element: <HomePage /> }],
  },
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  { path: '/privacy', element: <PrivacyPage /> }, // public: readable before signing up
  { path: '/share/:token', element: <SharedPage /> }, // public read-only link (PRD 4.18)
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { path: 'account', element: <AccountPage /> },
          {
            element: <RequireAuth roles={['contractor', 'admin']} />,
            children: [
              { path: 'projects/:projectId', element: <ProjectPage /> },
              { path: 'tiles', element: <TilesPage /> },
              { path: 'team', element: <TeamPage /> },
            ],
          },
          {
            element: <RequireAuth roles={['admin']} />,
            children: [{ path: 'admin', element: <AdminPage /> }],
          },
        ],
      },
    ],
  },
  { path: '*', element: <RedirectHome /> },
])
