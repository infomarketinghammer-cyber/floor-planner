import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useAuth } from '../auth/AuthContext.tsx'
import { usePrivacyInfo } from '../lib/privacy.ts'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="space-y-2 text-slate-700">{children}</div>
    </section>
  )
}

/**
 * How uploaded plans and project data are handled (PRD 4.14). The deployment-specific parts
 * (AI reading, encryption, location, email) come from the server's real settings.
 */
export function PrivacyPage() {
  const info = usePrivacyInfo()
  const { user } = useAuth()

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto max-w-3xl space-y-8 px-4 py-10">
        <div>
          <Link to="/" className="text-sm text-slate-500 hover:underline">
            ← Floor Planner
          </Link>
          <h1 className="mt-2 text-2xl font-semibold">Your plans and data</h1>
          <p className="mt-1 text-slate-600">
            Where your files are processed, what is stored, for how long, and how to delete it.
          </p>
        </div>

        <Section title="What your plans are used for">
          <p>
            Uploaded plans are used only to work out your estimate: reading room names and sizes, and showing results on
            the plan. They are not shared, sold or used for anything else. The one exception is the evaluation set, and
            only if you choose to add a plan to it (see below).
          </p>
        </Section>

        <Section title="Where files are processed">
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <strong>Digital PDFs and CAD drawings (DXF, DWG)</strong> are read on our own server. Their contents are
              not sent to any outside service.
            </li>
            {info === null ? (
              <li className="text-slate-500">Loading this service's settings…</li>
            ) : info.ai_reading_enabled ? (
              <li>
                <strong>Photos and scanned pages</strong> (pages without a text layer) are sent to {info.ai_provider}, an
                AI service, to read the room names and sizes. Its handling of that data is covered by Anthropic's{' '}
                <a className="text-brand-600 hover:underline" href="https://www.anthropic.com/legal/commercial-terms">
                  commercial terms
                </a>{' '}
                and{' '}
                <a className="text-brand-600 hover:underline" href="https://www.anthropic.com/legal/privacy">
                  privacy policy
                </a>
                .
              </li>
            ) : (
              <li>
                <strong>Photos and scanned pages</strong>: AI reading is turned off on this service, so they are not sent
                anywhere. You add their rooms by hand or import a room list.
              </li>
            )}
            {info?.email_enabled && (
              <li>
                <strong>Emailing a shopping list</strong> sends the list and the addresses you enter through{' '}
                {info.email_provider}, our email provider. The plan itself is never emailed.
              </li>
            )}
          </ul>
        </Section>

        <Section title="What is stored, and where">
          <p>
            Your account details (name, email, company, and your password stored only as a secure hash), the plan files
            you upload with page previews, your room list, tile and cost choices, and any feedback you give.
          </p>
          <ul className="list-disc space-y-1 pl-5">
            {info?.data_location && <li>Data is stored in {info.data_location}.</li>}
            <li>Connections to this service use HTTPS, so data is encrypted in transit.</li>
            {info && (
              <li>
                {info.files_encrypted_at_rest
                  ? 'Plan files and their page previews are encrypted at rest (AES-256).'
                  : 'Plan files are stored in the service database. File encryption at rest is not turned on for this service; ask its operator for details.'}
              </li>
            )}
            <li>
              Only you can open your projects. Administrators of this service can also open them, for example to help
              when you ask for support.
            </li>
          </ul>
        </Section>

        <Section title="How long files are kept">
          <p>
            <strong>{info?.retention ?? 'Kept until you delete them'}.</strong> Nothing is deleted automatically: your
            plans and projects stay available until you delete them. If the service operator keeps database backups,
            deleted data can remain in those backups until they expire.
          </p>
        </Section>

        <Section title="Deleting your data">
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <strong>A plan file</strong>: Delete on the file in a project. The file and its page previews are removed;
              rooms already read from it stay in the project.
            </li>
            <li>
              <strong>A project</strong>: Delete on the home page. Its plan files, rooms, choices and feedback are removed.
            </li>
            <li>
              <strong>Your account</strong>: on the{' '}
              {user ? (
                <Link to="/account" className="text-brand-600 hover:underline">
                  Account
                </Link>
              ) : (
                'Account'
              )}{' '}
              page. Everything above is removed for every project, along with your saved tiles and the account itself.
            </li>
          </ul>
        </Section>

        <Section title="Evaluation set (optional)">
          <p>
            After you confirm a project's rooms you can choose to share a copy of its plan and confirmed room list to help
            us test how well plans are read. It is off unless you tick the box for that project. The copy is kept until you
            remove it (from the project or your Account page) or delete your account, even if you delete the project.
          </p>
        </Section>
      </div>
    </div>
  )
}
