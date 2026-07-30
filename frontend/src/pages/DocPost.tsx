import { useState } from 'react'
import { Link, useLocation, Navigate } from 'react-router-dom'
import LandingNav from '../components/landing/LandingNav'
import { BRAND } from '../components/landing/brand'
import DemoModal from '../components/landing/DemoModal'

function Meta({ pillar, color, time }: { pillar: string, color: string, time: string }) {
  return <div className="mb-6 flex flex-wrap items-center gap-3"><span className="rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide text-white" style={{ backgroundColor: color }}>{pillar}</span><span className="text-sm text-slate-400">{time}</span></div>
}
function CTA() {
  const [showDemo, setShowDemo] = useState(false)
  return <div className="mt-10 rounded-2xl border p-8 text-center" style={{ borderColor: BRAND.dark + '33' }}><p className="mb-1 text-lg font-bold" style={{ color: BRAND.nearblack }}>See Accord on your own pipeline</p><button onClick={() => setShowDemo(true)} className="inline-flex items-center gap-2 rounded-lg px-6 py-3 text-sm font-semibold text-white mt-4" style={{ backgroundColor: BRAND.dark }}>Request a Demo</button>{showDemo && <DemoModal onClose={() => setShowDemo(false)} />}</div>
}
function Back() {
  return <div className="mt-10 border-t border-slate-100 pt-6"><Link to="/docs" className="text-sm font-medium hover:underline" style={{ color: BRAND.dark }}>← Back to all docs</Link></div>
}
function Section({ title, children }: { title: string, children: React.ReactNode }) {
  return <><h2>{title}</h2>{children}</>
}
function Fact({ label, value, note }: { label: string, value: string, note?: string }) {
  return <div className="my-4 rounded-xl border border-slate-200 p-4"><div className="text-xs font-bold uppercase tracking-wide text-slate-400">{label}</div><div className="mt-1 text-base font-semibold text-slate-800">{value}</div>{note && <div className="mt-1 text-sm text-slate-500">{note}</div>}</div>
}
function CodeBlock({ children }: { children: string }) {
  return <pre className="my-4 overflow-x-auto rounded-xl bg-slate-900 p-4 text-sm text-green-300"><code>{children}</code></pre>
}

function DocEnterpriseSecurity() {
  return (
    <article className="mx-auto max-w-3xl px-6 py-14">
      <Meta pillar="Enterprise Security" color="#1A3A5C" time="6 min read" />
      <h1 className="mb-6 text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>Enterprise Security Architecture</h1>
      <div className="prose prose-slate max-w-none">
        <p className="text-lg text-slate-600">Accord is engineered for regulated financial institutions handling mortgage applications, PII, and underwriting decisions subject to regulatory examination. Security is built into every layer — from authentication and authorization to tenant isolation, encryption, audit logging, and infrastructure resilience. This document describes controls currently implemented in production.</p>

        <h2>Authentication</h2>
        <p>Accord authenticates users using bcrypt password hashing with a unique salt generated for every password. Passwords are never stored in plaintext or reversibly encrypted. During authentication, submitted credentials are verified using bcrypt's constant-time comparison to mitigate timing attacks.</p>
        <CodeBlock>{`# core/auth/security.py
def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8")
    )`}</CodeBlock>
        <p>Every API endpoint requires JWT authentication. Authentication is performed before business logic executes, and authorization is evaluated independently for every request. No production endpoints bypass authentication.</p>

        <h2>Role-Based Access Control</h2>
        <p>Accord enforces RBAC across the application using predefined operational roles. A separate <code>super_admin</code> role is reserved exclusively for Accord platform operations.</p>
        <ul>
          <li>Underwriter</li>
          <li>Senior Underwriter</li>
          <li>Manager</li>
          <li>Compliance</li>
          <li>Administrator</li>
        </ul>
        <p>Permissions are evaluated on every request rather than cached in session state. Administrative <strong>View As</strong> functionality allows authorized administrators to troubleshoot customer issues while inheriting only the permissions of the impersonated user. Elevated privileges are never retained during impersonation.</p>

        <h2>PII Audit Logging</h2>
        <p>Every read of protected PII generates an immutable audit record through the Context Store layer. Logging is automatic at the platform level and cannot be disabled or bypassed by individual services. <strong>PRD §23.9 — pii_access_always_logged.</strong></p>
        <p><strong>Tracked fields:</strong> Social Security Number · Tax ID · Date of Birth · Address · Bank Account · Routing Number · Driver's License · First Name · Last Name</p>
        <CodeBlock>{`{
  "id": "uuid",
  "timestamp": "2026-07-28T14:22:31Z",
  "entity_type": "borrower",
  "entity_id": "APL-00001-P",
  "application_id": "APP-CL-M07",
  "pii_fields": ["ssn", "dob"],
  "caller": "income_verification",
  "action": "read"
}`}</CodeBlock>
        <p>Audit records are append-only and retained as compliance evidence. They support regulatory examinations, internal audit, security investigations, SOC 2 evidence collection, and daily PII access reporting.</p>

        <h2>PII Minimization</h2>
        <p>Full Social Security Numbers are never persisted in the document management layer. The platform stores a SHA-256 hash and the last four digits only. Identity verification operates against the cryptographic hash.</p>
        <ul>
          <li>Full SSNs are never written to PostgreSQL</li>
          <li>Full SSNs are never indexed</li>
          <li>Full SSNs are never included in application logs</li>
        </ul>

        <h2>Encryption</h2>
        <p><strong>At rest:</strong> All uploaded documents are stored in Amazon S3 using AES-256 SSE-KMS. Encryption is enforced at write time — unencrypted uploads are not possible through the application. S3 Versioning is enabled to preserve document history.</p>
        <p><strong>Secrets:</strong> Database credentials, Redis credentials, API keys, and third-party tokens are managed through AWS Secrets Manager. Secrets are never committed to source control, embedded in Docker images, stored in plaintext environment files, or hardcoded into ECS task definitions.</p>
        <p><strong>In transit:</strong> TLS terminates at the Application Load Balancer. No unencrypted HTTP traffic reaches application services. Internal services communicate over authenticated AWS networking.</p>

        <h2>Tenant Isolation</h2>
        <p>Every domain object contains a required <code>tenant_id</code>. All database queries are tenant-scoped before execution. Redis cache keys are namespaced per tenant to prevent cross-tenant cache access.</p>
        <ul>
          <li>Cross-tenant resource requests return <strong>404 Not Found</strong></li>
          <li>Tenant isolation is continuously verified through automated integration testing</li>
          <li>Per-tenant connection pools managed in <code>core/db/tenant_pool.py</code></li>
        </ul>

        <h2>Infrastructure</h2>
        <p>Accord runs on AWS: ECS Fargate · Application Load Balancer · Amazon Aurora PostgreSQL · RDS Proxy · S3 · SQS · AWS Secrets Manager. RDS Proxy manages connection pooling, allowing tasks to scale without exhausting PostgreSQL connections. Infrastructure operates within private AWS networking.</p>

        <h2>Resilience and Failure Handling</h2>
        <p>External dependencies are isolated behind circuit breakers. When a dependency becomes unavailable, Accord degrades gracefully rather than interrupting the underwriting workflow.</p>
        <ul>
          <li><strong>AI inference:</strong> Rule-based extraction continues for supported workflows</li>
          <li><strong>Amazon S3:</strong> Processing continues while document storage is retried</li>
          <li><strong>Amazon SQS:</strong> Workloads fall back to synchronous execution</li>
        </ul>

        <h2>Security Controls Summary</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Control</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['bcrypt password hashing', '✅ Implemented'],
                ['JWT authentication', '✅ Implemented'],
                ['Role-based access control (RBAC)', '✅ Implemented'],
                ['Immutable PII audit logging', '✅ Implemented'],
                ['Multi-tenant isolation', '✅ Implemented'],
                ['AES-256 SSE-KMS encryption', '✅ Implemented'],
                ['AWS Secrets Manager', '✅ Implemented'],
                ['Append-only audit trail', '✅ Implemented'],
                ['Circuit breaker architecture', '✅ Implemented'],
                ['Automated tenant isolation testing', '✅ Implemented'],
              ].map(([control, status]) => (
                <tr key={control}>
                  <td className="px-4 py-2.5 text-slate-700">{control}</td>
                  <td className="px-4 py-2.5 text-slate-700">{status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="my-6 rounded-xl border border-amber-200 bg-amber-50 p-5">
          <p className="mb-2 font-semibold text-amber-800">Planned Enhancements — Not Yet Implemented</p>
          <ul className="mb-0 mt-2 text-amber-900">
            <li>Field-level encryption within PostgreSQL</li>
            <li>Consent and regulatory tagging</li>
            <li>Automated secret rotation</li>
          </ul>
          <p className="mb-0 mt-3 text-sm text-amber-700">These are identified explicitly to provide an accurate view of Accord's current security posture. A lender evaluating Accord should know what is shipped versus what is planned.</p>
        </div>
      </div>
      <CTA /><Back />
    </article>
  )
}

function DocSOC2() {
  return (
    <article className="mx-auto max-w-3xl px-6 py-14">
      <Meta pillar="SOC 2-Ready" color="#7C2D12" time="6 min read" />
      <h1 className="mb-6 text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>SOC 2-Ready Audit Architecture</h1>
      <div className="prose prose-slate max-w-none">
        <p className="text-lg text-slate-600">Every AI decision Accord makes is recorded, reconstructable, and exportable for regulatory examination. The audit architecture is not a reporting layer added after the fact — it is a core component of the decision engine itself. Every underwriting decision can be traced from the original application data through AI analysis, human review, and final disposition without relying on reconstructed logs or inferred system state. This document describes the audit controls currently implemented in production.</p>

        <h2>Append-Only Decision Trace</h2>
        <p>Every AI decision generates exactly one immutable DecisionTrace record. Decision traces are append-only — once written, they cannot be modified or overwritten. If a human underwriter later approves, overrides, or escalates the recommendation, that action is recorded separately while preserving the original AI decision.</p>
        <CodeBlock>{`# core/trace/trace_writer.py
async def write(self, trace: DecisionTrace) -> UUID:
    # Reject duplicate trace IDs — append-only enforced
    if trace.trace_id in self._traces:
        raise ValueError(
            f"trace_id {trace.trace_id} already written"
        )

async def attach_human_review(self, trace_id: UUID, review: HumanReview):
    # Original trace remains immutable
    updated = existing.model_copy(
        update={"human_review": review}
    )`}</CodeBlock>
        <p>The PostgreSQL implementation preserves the append-only contract by storing human reviews separately from the original AI decision. The original AI recommendation — including reasoning, confidence score, evidence, and policy evaluation — never changes.</p>

        <h2>Immutable Decision Snapshots</h2>
        <p>Immediately after each decision is committed, Accord stores a frozen persona bundle representing the exact information available to the AI agent at decision time.</p>
        <ul>
          <li><strong>Entity snapshot</strong> — borrower and loan attributes evaluated</li>
          <li><strong>Evidence snapshot</strong> — supporting documents and confidence scores</li>
          <li><strong>Rules snapshot</strong> — underwriting rules and policy versions in effect</li>
          <li><strong>Upstream snapshot</strong> — outputs from previously executed AI agents</li>
        </ul>
        <p>During live underwriting, the AI operates entirely from in-memory decision context. During replay or examination, Accord reconstructs decisions directly from the immutable snapshot without re-running AI models or rebuilding state from current data. This enables deterministic replay for regulatory examinations, investor due diligence, repurchase defense, internal quality assurance, and model validation.</p>

        <h2>Decision Scale</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Metric</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Production</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Specialized AI agents per loan', '14'],
                ['Decisions across 63 active loans', '882'],
                ['Decision output', 'Outcome, confidence score, regulatory citation, evidence references'],
                ['Immutable snapshot', 'One persona bundle per decision'],
                ['Human overrides', 'Fully tracked with user, role, timestamp, and rationale'],
                ['Missing audit snapshots', '0 — audit invariant maintained'],
              ].map(([metric, value]) => (
                <tr key={metric}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{metric}</td>
                  <td className="px-4 py-2.5 text-slate-600">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Human Review and Overrides</h2>
        <p>Every manual action — approvals, denials, escalations, condition requests, and overrides — is recorded independently from the original AI recommendation. The audit trail always preserves both the original AI recommendation and the subsequent human decision.</p>
        <CodeBlock>{`{
  "application_id": "APP-CL-ARM04",
  "action_type": "override_approve",
  "actor_user_id": "senioruw@capitalloans.com",
  "actor_role": "senior_uw",
  "rationale": "Exception granted — compensating factors documented",
  "timestamp": "2026-07-28T15:44:21Z",
  "decision_output_id": "uuid"
}`}</CodeBlock>

        <h2>High Availability and Data Durability</h2>
        <p>Accord operates on Amazon Aurora PostgreSQL Multi-AZ with automated failover. Decision processing is idempotent using the combination of application identifier and decision identifier — retried or redelivered messages never generate duplicate decisions.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Objective</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Target</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['RTO (Multi-AZ failover)', '30 minutes'],
                ['RTO (Point-in-time restore)', '2 hours'],
                ['RPO (Multi-AZ)', '5 minutes'],
                ['RPO (Point-in-time restore)', '1 hour'],
              ].map(([objective, target]) => (
                <tr key={objective}>
                  <td className="px-4 py-2.5 text-slate-700">{objective}</td>
                  <td className="px-4 py-2.5 text-slate-600">{target}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul>
          <li>Multi-AZ Aurora with automated failover</li>
          <li>Amazon RDS Proxy connection pooling</li>
          <li>Amazon SQS dead-letter queues</li>
          <li>Amazon ECS Fargate autoscaling</li>
          <li>S3 Versioning with Retain deletion policy</li>
          <li>Aurora Deletion Protection + 7-day automated backups</li>
          <li>Circuit breakers on all external dependencies</li>
        </ul>

        <h2>Point-in-Time Context Replay</h2>
        <p>Every context assembly is versioned and stored as an immutable snapshot. Accord can reconstruct the precise decision context that existed at any point in time without relying on current application state.</p>
        <CodeBlock>{`GET /application/{id}/context/at/{timestamp}
# Returns the exact context object at that moment
# Replay includes: borrower data, loan attributes, supporting evidence,
# policy rules, AI recommendations, and human actions`}</CodeBlock>

        <h2>Examiner Export</h2>
        <p>Accord generates an examiner-ready audit package directly from the platform. The export includes every AI recommendation, confidence scores, regulatory citations, supporting evidence references, complete human review history, override rationale, and approval authority chain. Supported formats: CSV and PDF.</p>

        <h2>SOC 2 Controls</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Control</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Append-only decision trace', '✅ Implemented'],
                ['Immutable decision snapshots', '✅ Implemented'],
                ['Human review side-channel', '✅ Implemented'],
                ['Immutable audit trail', '✅ Implemented'],
                ['Point-in-time context replay', '✅ Implemented'],
                ['Multi-AZ database architecture', '✅ Implemented'],
                ['Idempotent decision processing', '✅ Implemented'],
                ['Dead-letter queues', '✅ Implemented'],
                ['Examiner export package', '✅ Implemented'],
                ['Circuit breakers', '✅ Implemented'],
              ].map(([control, status]) => (
                <tr key={control}>
                  <td className="px-4 py-2.5 text-slate-700">{control}</td>
                  <td className="px-4 py-2.5 text-slate-700">{status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="my-6 rounded-xl border border-amber-200 bg-amber-50 p-5">
          <p className="mb-2 font-semibold text-amber-800">Planned Enhancements — Not Yet Implemented</p>
          <ul className="mb-0 mt-2 text-amber-900">
            <li>Formal SOC 2 Type II audit (controls implemented; independent audit not yet completed)</li>
            <li>Full 14-agent replay execution (current replay reconstructs decision state without re-executing every agent)</li>
            <li>Automated secrets rotation</li>
          </ul>
          <p className="mb-0 mt-3 text-sm text-amber-700">Accord is transparent about what is shipped versus what is planned. A lender or auditor evaluating SOC 2 readiness should know the difference before beginning due diligence.</p>
        </div>
      </div>
      <CTA /><Back />
    </article>
  )
}

function DocHMDA() {
  return (
    <article className="mx-auto max-w-3xl px-6 py-14">
      <Meta pillar="HMDA & Fair Lending" color="#4A1A5C" time="7 min read" />
      <h1 className="mb-6 text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>HMDA & Fair Lending Built Into Every Underwriting Decision</h1>
      <div className="prose prose-slate max-w-none">
        <p className="text-lg text-slate-600">HMDA reporting and fair lending monitoring are core capabilities of Accord's decision engine — not separate compliance modules or post-processing workflows. Every underwriting decision automatically generates the data required for HMDA reporting while maintaining strict separation between regulatory reporting information and the underwriting decision itself. Applicant demographic information is collected solely for compliance reporting and fair lending monitoring and is never used to determine credit eligibility.</p>

        <h2>Automatic HMDA LAR Generation</h2>
        <p>Every completed underwriting decision automatically produces a HMDA Loan Application Register (LAR) record. Records are generated after the underwriting outcome is finalized, ensuring that reporting accurately reflects the completed credit decision.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Field</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Action Taken', 'Final underwriting outcome'],
                ['Loan Amount', 'Loan entity data'],
                ['Loan Type', 'Product selection'],
                ['Denial Reasons', 'AI decision outputs mapped to HMDA denial codes 1–9'],
                ['Applicant Race', 'HMDA demographic record — never used in underwriting'],
                ['Applicant Sex', 'HMDA demographic record — never used in underwriting'],
                ['Applicant Ethnicity', 'HMDA demographic record — never used in underwriting'],
              ].map(([field, source]) => (
                <tr key={field}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{field}</td>
                  <td className="px-4 py-2.5 text-slate-600">{source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Demographic Firewall</h2>
        <p>Accord enforces a strict architectural separation between underwriting decisions and applicant demographic information. Protected demographic fields are not available to the AI decision engine during credit evaluation.</p>
        <ul>
          <li>Race is excluded from underwriting context</li>
          <li>Ethnicity is excluded from underwriting context</li>
          <li>Sex is excluded from underwriting context</li>
          <li>HMDA demographic records are attached only after the underwriting outcome has been finalized</li>
        </ul>
        <p>This architectural separation ensures demographic information cannot influence underwriting recommendations. Citation: <strong>ECOA 12 CFR 202</strong></p>

        <h2>Fair Lending Monitoring — Four-Fifths Rule</h2>
        <p>Accord continuously evaluates portfolio outcomes for potential fair lending disparities across race, sex, and ethnicity using the EEOC Four-Fifths Rule (80% Rule). Approval rates are compared against the reference group — the group with the highest approval rate.</p>
        <CodeBlock>{`{
  "protected_class": "race",
  "status": "no_disparate_impact",
  "reference_group": "White",
  "sample_size": 63,
  "four_fifths_threshold": 0.80,
  "has_disparate_impact": false
}
// Citation: ECOA 12 CFR 202 + EEOC 29 CFR 1607.4(D)`}</CodeBlock>
        <p>The Four-Fifths Rule serves as an analytical screening tool to identify potential disparities requiring further review. It does not by itself determine regulatory compliance or establish a fair lending violation.</p>

        <h2>Statistical Safeguards</h2>
        <p>Accord avoids producing misleading fair lending analyses by validating data quality before calculating disparity metrics. When these conditions occur, the platform reports insufficient_data rather than producing statistically unreliable results.</p>
        <ul>
          <li><strong>Insufficient sample size</strong> — portfolios with fewer than 30 observations</li>
          <li><strong>Missing demographic information</strong> — when applicants decline to provide demographic data</li>
          <li><strong>Single-group populations</strong> — where meaningful comparison groups do not exist</li>
        </ul>

        <h2>Exception Monitoring</h2>
        <p>Accord monitors underwriting exceptions independently from standard approval decisions. Exception approvals can be analyzed by protected class to identify differences in exception grant rates across demographic groups, providing additional visibility into underwriting consistency beyond standard approval metrics.</p>

        <h2>Adverse Action Compliance</h2>
        <p>For denied applications, Accord automatically tracks adverse action requirements under Regulation B. The platform records the completed application date, 30-day notification deadline, denial reasons, mapped HMDA denial codes, and adverse action status — enabling compliance teams to monitor pending notices before regulatory deadlines expire. Citation: <strong>ECOA 12 CFR 1002.9</strong></p>

        <h2>Portfolio Reporting — Capital Loans Mortgage</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Metric</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Total Applications', '63'],
                ['Originated', '33 ($12.14M)'],
                ['Denied', '26 ($11.49M)'],
                ['Denial Rate', '44.1%'],
                ['HMDA Record Completeness', '100%'],
                ['Pending Adverse Action Notices', '26'],
                ['Fair Lending Analyses', 'Race, Sex, Ethnicity — 3 independent analyses'],
              ].map(([metric, value]) => (
                <tr key={metric}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{metric}</td>
                  <td className="px-4 py-2.5 text-slate-600">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Compliance Controls</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Control</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Automatic HMDA LAR generation', '✅ Implemented'],
                ['Demographic firewall', '✅ Implemented'],
                ['Automated denial reason mapping', '✅ Implemented'],
                ['Four-Fifths Rule analysis', '✅ Implemented'],
                ['Statistical validity safeguards', '✅ Implemented'],
                ['Exception grant rate monitoring', '✅ Implemented'],
                ['Adverse action deadline tracking', '✅ Implemented'],
                ['Portfolio-level fair lending reporting', '✅ Implemented'],
              ].map(([control, status]) => (
                <tr key={control}>
                  <td className="px-4 py-2.5 text-slate-700">{control}</td>
                  <td className="px-4 py-2.5 text-slate-700">{status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="my-6 rounded-xl border border-amber-200 bg-amber-50 p-5">
          <p className="mb-2 font-semibold text-amber-800">Planned Enhancements — Not Yet Implemented</p>
          <ul className="mb-0 mt-2 text-amber-900">
            <li>Community Reinvestment Act (CRA) assessment integration</li>
            <li>Configurable fair lending thresholds by product or portfolio segment</li>
            <li>Automated HMDA LAR submission workflow to the CFPB</li>
          </ul>
          <p className="mb-0 mt-3 text-sm text-amber-700">HMDA and fair lending examinations reward preparation. These gaps are documented so compliance teams can plan accordingly rather than discover them during an exam.</p>
        </div>
      </div>
      <CTA /><Back />
    </article>
  )
}

function DocCompliant() {
  return (
    <article className="mx-auto max-w-3xl px-6 py-14">
      <Meta pillar="Compliant by Design" color="#1B4332" time="8 min read" />
      <h1 className="mb-6 text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>Compliant by Design: Model Risk Management & Regulatory Architecture</h1>
      <div className="prose prose-slate max-w-none">
        <p className="text-lg text-slate-600">Accord is designed to make underwriting decisions transparent, explainable, and auditable. Every lending decision is driven by version-controlled policy catalogs, documented AI agents, and regulatory citations that can be reviewed by auditors, model risk teams, and examiners. Every decision answers four fundamental questions: What rule was applied? Where did the rule originate? Why was the decision made? Which evidence supported it?</p>

        <h2>Three-Layer Rule Hierarchy</h2>
        <p>Accord evaluates every underwriting decision through a structured hierarchy of policy sources. When multiple rules apply, Accord evaluates them in accordance with the configured policy hierarchy. Every applied rule is documented with its source and regulatory citation.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Layer</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Purpose</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Authority</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Federal Regulations', 'Statutory and regulatory requirements — FLOOR', 'CFPB, HUD, VA'],
                ['Agency Guidelines', 'Program eligibility and underwriting guidance', 'Fannie Mae, Freddie Mac, FHA, VA'],
                ['Lender Overlays', 'Institution-specific credit policy — always wins', 'Individual lender credit policy'],
              ].map(([layer, purpose, authority]) => (
                <tr key={layer}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{layer}</td>
                  <td className="px-4 py-2.5 text-slate-600">{purpose}</td>
                  <td className="px-4 py-2.5 text-slate-600">{authority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Policy Catalog Architecture</h2>
        <p>Accord maintains underwriting policy in centralized, version-controlled catalogs rather than application code. Automated verification ensures every production deployment validates catalog integrity before release.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Catalog</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Rules</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Coverage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Agency Guidelines', '114', 'Fannie Mae 91 / FHA 13 / VA 8 / Freddie Mac 2'],
                ['Federal Regulations', '23', 'CFPB / HUD / VA'],
                ['Lender Overlay Rules', '6', 'Meridian 4 / Summit 2'],
                ['Catalog verify gate', '59/59', 'scripts/verify_catalogue_ready.py — exit 0'],
              ].map(([catalog, rules, coverage]) => (
                <tr key={catalog}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{catalog}</td>
                  <td className="px-4 py-2.5 text-slate-600">{rules}</td>
                  <td className="px-4 py-2.5 text-slate-600">{coverage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>No Hardcoded Lending Thresholds</h2>
        <p>Credit policy is managed through configurable catalogs instead of application logic. Separating policy from software allows institutions to modify underwriting requirements through governed policy updates while preserving version history and auditability. Examples include minimum credit scores, maximum DTI ratios, LTV limits, reserve requirements, program eligibility criteria, and lender overlays.</p>
        <p>If a rule is missing from the catalog, the system logs a WARNING and uses a documented safe default — never a silent assumption. Every resolver method returns data_source and missing_inputs so gaps are explicit on the workbench.</p>

        <h2>SR 11-7 Model Risk Management</h2>
        <p>Accord's AI architecture is designed to support the model governance principles described in OCC/Federal Reserve SR 11-7. Every AI agent includes documented model governance artifacts covering intended use, assumptions, inputs, outputs, limitations, and monitoring approach.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Risk Tier</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Models</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Monitoring Cadence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['High', '8', 'Quarterly drift review + annual validation'],
                ['Medium', '4', 'Semi-annual drift review + biennial validation'],
                ['Low', '2', 'Annual drift review'],
              ].map(([tier, models, cadence]) => (
                <tr key={tier}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{tier}</td>
                  <td className="px-4 py-2.5 text-slate-600">{models}</td>
                  <td className="px-4 py-2.5 text-slate-600">{cadence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>Ongoing monitoring includes model drift detection, accuracy back-testing, champion/challenger evaluation, and portfolio performance monitoring.</p>

        <h2>Multi-Agent Decision Architecture</h2>
        <p>Accord evaluates each mortgage application through 14 specialized AI agents organized into two decision stages. Across the current Capital Loans Mortgage portfolio, these agents generated 882 individual AI decisions supporting 63 active mortgage applications.</p>
        <CodeBlock>{`Wave 1 — Verification
  income_verification · credit_assessment · asset_verification
  fraud_screening · employment_reconciliation · compliance_check

Wave 2 — Underwriting
  dti_calculation · ltv_assessment · product_eligibility · title_assessment
  rate_pricing · approval_routing · closing_readiness · underwriting_decision`}</CodeBlock>

        <h2>ATR/QM Compliance</h2>
        <p>Every application is automatically evaluated against Ability-to-Repay (ATR) and Qualified Mortgage (QM) requirements. Each determination includes supporting regulatory citations and becomes part of the permanent audit record.</p>
        <ul>
          <li>Eight-factor ATR evaluation</li>
          <li>Debt-to-income analysis — safe harbor threshold 43%</li>
          <li>Points and fees threshold — 3%</li>
          <li>Higher-Priced Mortgage Loan (HPML) review — 150bps</li>
          <li>Citation: <strong>12 CFR 1026.43</strong></li>
        </ul>

        <h2>Policy Simulation</h2>
        <p>Accord enables lenders to evaluate proposed policy changes before they affect production underwriting. Rather than estimating portfolio impact, the simulator identifies the specific loans affected, the resulting underwriting outcome, and the reason each decision changes.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Scenario</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Loans Affected</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Volume</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Approval Rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['+200bps rate stress', '33 of 63', '$9.4M', '74.6% → 33.3%'],
                ['DTI 43% → 36%', '33 of 63', '$12.7M', '74.6% → 22.2%'],
              ].map(([scenario, loans, volume, rate]) => (
                <tr key={scenario}>
                  <td className="px-4 py-2.5 text-slate-700">{scenario}</td>
                  <td className="px-4 py-2.5 text-slate-600">{loans}</td>
                  <td className="px-4 py-2.5 text-slate-600">{volume}</td>
                  <td className="px-4 py-2.5 text-slate-600">{rate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Regulatory Traceability</h2>
        <p>Every underwriting recommendation includes direct references to the governing policy or regulation. These citations are embedded directly into the decision record, providing immediate traceability for underwriters, quality control reviewers, and regulatory examiners.</p>
        <ul>
          <li>Fannie Mae Selling Guide</li>
          <li>Freddie Mac Seller/Servicer Guide</li>
          <li>FHA Handbook</li>
          <li>VA Lender Handbook</li>
          <li>Equal Credit Opportunity Act (Regulation B)</li>
          <li>Truth in Lending Act / ATR-QM Rule (12 CFR 1026.43)</li>
          <li>Uniform Guidelines on Employee Selection Procedures (Four-Fifths Rule)</li>
          <li>OCC/Federal Reserve SR 11-7</li>
        </ul>

        <h2>Governance Controls</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Control</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Three-layer policy hierarchy', '✅ Implemented'],
                ['Version-controlled rule catalogs', '✅ Implemented'],
                ['Zero hardcoded lending thresholds', '✅ Implemented'],
                ['Regulatory citations per decision', '✅ Implemented'],
                ['AI model cards (SR 11-7)', '✅ Implemented'],
                ['Multi-agent decision architecture', '✅ Implemented'],
                ['ATR/QM automated evaluation', '✅ Implemented'],
                ['Policy simulation', '✅ Implemented'],
                ['Drift monitoring', '✅ Implemented'],
                ['Champion/challenger testing', '✅ Implemented'],
              ].map(([control, status]) => (
                <tr key={control}>
                  <td className="px-4 py-2.5 text-slate-700">{control}</td>
                  <td className="px-4 py-2.5 text-slate-700">{status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="my-6 rounded-xl border border-amber-200 bg-amber-50 p-5">
          <p className="mb-2 font-semibold text-amber-800">Planned Enhancements — Not Yet Implemented</p>
          <ul className="mb-0 mt-2 text-amber-900">
            <li>Independent SR 11-7 model validation (controls implemented; third-party validation not yet completed)</li>
            <li>Enhanced variable-income analysis (overtime, bonus, commission)</li>
            <li>Full 14-agent deterministic replay</li>
            <li>Expanded manual-review routing for complex approval conflicts</li>
          </ul>
          <p className="mb-0 mt-3 text-sm text-amber-700">Model risk examiners expect honesty about validation gaps. These items are documented so risk teams know exactly where independent validation work remains before an OCC or CFPB examination.</p>
        </div>
      </div>
      <CTA /><Back />
    </article>
  )
}

function DocGettingStarted() {
  return (
    <article className="mx-auto max-w-3xl px-6 py-14">
      <Meta pillar="Start Here" color="#166534" time="7 min read" />
      <h1 className="mb-6 text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>Getting Started with Accord</h1>
      <div className="prose prose-slate max-w-none">
        <p className="text-lg text-slate-600">Accord is an AI decision layer for mortgage lenders. It works alongside your existing Loan Origination System (LOS) to analyze loan applications, automate underwriting reviews, and generate structured, auditable recommendations before an underwriter begins manual review.</p>
        <p>Rather than replacing your LOS, Accord complements your existing technology by evaluating every loan against agency guidelines, lender overlays, and regulatory requirements while maintaining a complete audit trail for every decision.</p>
        <p>Each AI recommendation includes structured underwriting findings, supporting evidence, confidence scores, regulatory citations, recommended next actions, and complete decision history. Human underwriters remain in control of the final lending decision. Accord provides consistent analysis and documentation to support that process.</p>

        <h2>Before You Begin</h2>
        <p>Before onboarding your organization, gather the following information:</p>
        <ul>
          <li>Company information and NMLS number</li>
          <li>State licensing information</li>
          <li>Loan product matrix</li>
          <li>Credit policy and lender overlays</li>
          <li>Current pricing or rate sheets</li>
          <li>Sample loan files for validation</li>
          <li>LOS export files or integration details</li>
        </ul>

        <h2>Onboarding Overview</h2>
        <p>Accord is configured in a series of guided steps that establish your organization's underwriting policies, loan products, and operational settings before loan files are evaluated.</p>

        <h2>Step 1 — Create Your Organization</h2>
        <p>Create your Accord tenant by entering your company's information, NMLS identifier, lending channels, and administrative contacts. This establishes an isolated environment for your organization and forms the foundation for all configuration and data management.</p>

        <h2>Step 2 — Configure State Licensing</h2>
        <p>Select the states where your organization is licensed to originate loans. Accord uses this information when evaluating state-specific compliance requirements throughout the underwriting process.</p>

        <h2>Step 3 — Configure Loan Products</h2>
        <p>Add the mortgage products your organization offers. Each product includes its own eligibility requirements, pricing configuration, and applicable agency guidelines.</p>
        <ul>
          <li>Conventional</li>
          <li>FHA</li>
          <li>VA</li>
          <li>USDA</li>
          <li>Jumbo</li>
          <li>Adjustable-Rate Mortgages (ARMs)</li>
          <li>Portfolio products</li>
        </ul>

        <h2>Step 4 — Configure Credit Policy</h2>
        <p>Import or configure your underwriting policy. Accord combines agency requirements with your organization's overlays. All policy rules are versioned and auditable.</p>
        <ul>
          <li>Minimum credit scores</li>
          <li>Maximum debt-to-income ratios</li>
          <li>Maximum loan-to-value limits</li>
          <li>Reserve requirements</li>
          <li>Documentation standards</li>
          <li>Internal lending overlays</li>
        </ul>

        <h2>Step 5 — Configure Exception Policies</h2>
        <p>Define how policy exceptions should be handled. These settings determine when loans are routed for additional review rather than automatically recommended.</p>
        <ul>
          <li>Compensating factor requirements</li>
          <li>Exception thresholds</li>
          <li>Approval authority levels</li>
          <li>Escalation workflows</li>
          <li>Documentation requirements</li>
        </ul>

        <h2>Step 6 — Upload Pricing</h2>
        <p>Import your pricing information. The pricing engine uses this information when evaluating loan eligibility and payment calculations.</p>
        <ul>
          <li>Base rates</li>
          <li>Loan-Level Price Adjustments (LLPAs)</li>
          <li>Product pricing</li>
          <li>ARM pricing</li>
          <li>Investor adjustments</li>
        </ul>

        <h2>Step 7 — Connect Your Loan Origination System</h2>
        <p>Accord integrates with your existing LOS, allowing your organization to continue using its current workflow while adding AI-powered underwriting analysis. During implementation, Accord is configured to synchronize loan applications, import borrower and property information, map LOS fields to Accord's canonical mortgage data model, and return AI recommendations and conditions to the originating loan file.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Integration</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Encompass LOS', 'Coming Soon'],
                ['BytePro', 'Coming Soon'],
                ['Claude AI (Anthropic)', '✅ Live — powers all 14 agents'],
                ['AWS (ECS, Aurora, S3, SQS)', '✅ Live — production infrastructure'],
                ['HMDA filing (CFPB)', 'Manual export — automated submission planned'],
              ].map(([integration, status]) => (
                <tr key={integration}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{integration}</td>
                  <td className="px-4 py-2.5 text-slate-600">{status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Step 8 — Import and Evaluate Your First Loan</h2>
        <p>Once configuration is complete, import one or more representative loan files to validate your configuration. For each application, Accord automatically analyzes income, credit, assets, employment, fraud risk, compliance, DTI, LTV, product eligibility, title, pricing, approval routing, closing readiness, and produces a final underwriting recommendation.</p>
        <p>Each evaluation produces a structured decision package containing findings, confidence scores, regulatory citations, supporting evidence, and recommended next actions. Review these recommendations with your underwriting team before enabling production workflows.</p>

        <h2>Platform Studio</h2>
        <p>Platform Studio is the administrative workspace used to manage your Accord environment after onboarding. Changes are versioned and immediately available to the AI decision engine.</p>
        <ul>
          <li>Organization settings</li>
          <li>Users and roles</li>
          <li>State licensing</li>
          <li>Loan products</li>
          <li>Credit policy and lender overlays</li>
          <li>Approval authorities</li>
          <li>Workflow configuration</li>
          <li>Field mappings</li>
          <li>Import settings</li>
        </ul>

        <h2>Next Steps</h2>
        <p>After completing onboarding, explore the remaining documentation to learn more about the platform.</p>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Guide</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['The Accord Data Model', '/docs/data-model', true],
                ['HMDA & Fair Lending', '/docs/hmda-fair-lending', true],
                ['Enterprise Security', '/docs/enterprise-security', true],
                ['Audit Trail & SOC 2 Readiness', '/docs/soc2-ready', true],
                ['Model Risk & Compliance', '/docs/compliant-by-design', true],
                ['AI Underwriting', '', false],
                ['Policy Simulation', '', false],
                ['API Reference', '', false],
              ].map(([guide, path, available]) => (
                <tr key={guide as string}>
                  <td className="px-4 py-2.5 text-slate-700">
                    {available && path ? (
                      <a href={path as string} className="font-medium hover:underline" style={{ color: '#166534' }}>{guide as string}</a>
                    ) : (
                      <span className="font-medium">{guide as string}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">
                    {available ? '✅ Available' : '🔜 Coming soon'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <CTA /><Back />
    </article>
  )
}

function DocDataModel() {
  return (
    <article className="mx-auto max-w-3xl px-6 py-14">
      <Meta pillar="Data Model" color="#0F4C75" time="6 min read" />
      <h1 className="mb-6 text-[32px] font-bold leading-[1.2] tracking-[-0.02em] md:text-[40px]" style={{ color: BRAND.nearblack }}>The Accord Data Model</h1>
      <div className="prose prose-slate max-w-none">
        <p className="text-lg text-slate-600">Accord organizes mortgage underwriting around eight core entities that represent every stage of the lending lifecycle — from document ingestion through final disposition. Together, these entities create a deterministic, auditable decision engine that transforms loan data into explainable underwriting recommendations.</p>
        <p>Unlike a traditional Loan Origination System (LOS), which serves as the system of record, Accord serves as the system of decision. Every AI recommendation, human action, and regulatory outcome is tied back to these core entities and preserved in an immutable audit trail.</p>

        <h2>Core Entities</h2>

        <p><strong>1. Loan File</strong><br />The Loan File is the root object for every underwriting workflow. It represents a single mortgage application, its borrowers, documents, decisions, conditions, and audit history. Each Loan File has a unique application ID, a lender tenant, and a lifecycle from intake through disposition. Every object in Accord belongs to exactly one Loan File.</p>

        <p><strong>2. Entity State</strong><br />The Entity State is the authoritative representation of the loan after document reconciliation. Rather than forcing downstream AI agents to interpret multiple versions of the same information, Accord consolidates extracted data from every available source — LOS, credit reports, income documents, bank statements, AUS findings, and identity documents — into a single verified record. When documents conflict, the Entity State stores the reconciled value, confidence score, supporting evidence, and originating source. This becomes the single source of truth for every underwriting decision.</p>

        <p><strong>3. Evidence Bundle</strong><br />Every AI decision is made using an Evidence Bundle — a frozen snapshot of everything an individual AI agent needs at the exact moment a decision is made. This includes reconciled Entity State values, document confidence scores, applicable regulatory rules, lender overlays, upstream AI decisions, and supporting evidence references. AI agents never query the database directly. Because the bundle is immutable, every decision can be replayed exactly as it occurred during an audit, quality control review, or regulatory examination.</p>

        <p><strong>4. Decision</strong><br />A Decision is the structured output produced by one AI agent for one Loan File. Every Loan File generates fourteen Decisions — one from each specialized underwriting agent. Each Decision includes: outcome (Recommend, Escalate, or Block), confidence score, regulatory citation, supporting evidence, decision signals, Evidence Bundle reference, and timestamp. Together, these Decisions form the complete AI underwriting recommendation.</p>

        <p><strong>5. Rule</strong><br />Every lending requirement in Accord is represented as a version-controlled Rule. Rules are loaded dynamically from the policy catalogue rather than embedded in application code, allowing regulatory updates and lender overlays without software changes. Rules exist within three hierarchical layers:</p>
        <ul>
          <li><strong>Federal Regulations</strong> — Consumer protection laws and federal requirements. These rules cannot be overridden.</li>
          <li><strong>Agency Guidelines</strong> — Program requirements published by Fannie Mae, Freddie Mac, FHA, VA, and USDA.</li>
          <li><strong>Lender Overlays</strong> — Institution-specific underwriting policies. When an overlay is stricter than an agency guideline, the overlay governs.</li>
        </ul>
        <p>Every applied rule records its source, citation, effective date, version, and last update.</p>

        <p><strong>6. Condition</strong><br />A Condition represents an unresolved item preventing a Loan File from advancing. Conditions are generated automatically when required documentation, verification, or policy requirements remain outstanding — missing income documentation, identity verification failure, title defects, AUS not run, rate lock required, missing disclosures. Each Condition includes type, severity, governing rule, recommended action, and current status. Conditions remain open until resolved or formally waived.</p>

        <p><strong>7. Exception</strong><br />An Exception is a documented request to originate a loan outside standard lender policy. Exceptions typically occur when a loan violates an overlay but includes sufficient compensating factors — strong credit profile, low DTI, significant cash reserves, long employment history. Every Exception follows a governed workflow: Requested → Under Review → Approved or Denied. Approval authority is determined automatically based on the exception score and lender policy.</p>

        <p><strong>8. Audit Trail</strong><br />The Audit Trail is the permanent record of every AI and human decision made on a Loan File. It includes append-only Decision traces, immutable Evidence Bundle snapshots, human overrides, approval rationale, condition history, exception workflow, HMDA records, and Adverse Action Notice tracking. Original AI decisions are never modified. Human actions are recorded alongside the AI recommendation, preserving a complete history for regulatory examinations, investor reviews, quality control, and repurchase defense.</p>

        <h2>How Accord Processes a Loan</h2>
        <CodeBlock>{`Loan File
        │
        ▼
Document Ingestion
        │
        ▼
Entity State Built
        │
        ▼
Evidence Bundle Created
        │
        ▼
14 AI Agents Evaluate
        │
        ▼
14 Structured Decisions
        │
        ▼
Rule Hierarchy Applied
(Federal → Agency → Overlay)
        │
        ▼
Conditions / Exceptions Generated
        │
        ▼
Final Underwriting Decision
        │
        ▼
Audit Trail Written`}</CodeBlock>
        <p>The underwriting_decision agent consumes the outputs from all thirteen upstream agents, applies the complete rule hierarchy, and produces the final underwriting recommendation — along with a HMDA LAR record, Adverse Action Notice (when applicable), regulatory citations, and complete audit evidence.</p>

        <h2>Entity Reference</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Entity</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Storage</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Relationship</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Loan File', 'entity_states', 'Root object for every application'],
                ['Entity State', 'entity_states', 'One authoritative record per Loan File'],
                ['Evidence Bundle', 'persona_bundles', 'Immutable snapshot for each AI decision'],
                ['Decision', 'decision_outputs', 'Fourteen decisions per Loan File'],
                ['Rule', 'regulatory_rules / agency_guidelines / overlay_rules', 'Three-layer policy catalogue'],
                ['Condition', 'loan_condition_instances', 'Outstanding requirements preventing progression'],
                ['Exception', 'loan_exceptions', 'Policy exception workflow'],
                ['Audit Trail', 'decision_trace / loan_actions', 'Immutable history of AI and human decisions'],
              ].map(([entity, storage, relationship]) => (
                <tr key={entity}>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{entity}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{storage}</td>
                  <td className="px-4 py-2.5 text-slate-600">{relationship}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>The Fourteen AI Underwriting Agents</h2>
        <div className="my-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Wave</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Agent</th>
                <th className="px-4 py-3 text-left font-semibold text-slate-700">Responsibility</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['1 — Verification', 'Income Verification', 'Validate qualifying income and resolve variable or self-employed income'],
                ['1 — Verification', 'Credit Assessment', 'Evaluate credit profile, tradelines, and derogatory history'],
                ['1 — Verification', 'Asset Verification', 'Verify reserves, assets, and large deposits'],
                ['1 — Verification', 'Fraud Screening', 'Evaluate identity risk and fraud indicators'],
                ['1 — Verification', 'Employment Reconciliation', 'Confirm employment continuity and resolve inconsistencies'],
                ['1 — Verification', 'Compliance Check', 'Evaluate ATR/QM, HMDA, fair lending, and regulatory requirements'],
                ['2 — Decision', 'DTI Calculation', 'Calculate qualifying debt-to-income ratios'],
                ['2 — Decision', 'LTV Assessment', 'Calculate LTV and CLTV while identifying exceptions'],
                ['2 — Decision', 'Product Eligibility', 'Determine program eligibility'],
                ['2 — Decision', 'Title Assessment', 'Review title status and lien conditions'],
                ['2 — Decision', 'Rate Pricing', 'Calculate pricing adjustments and qualifying rates'],
                ['2 — Decision', 'Approval Routing', 'Determine required approval authority'],
                ['2 — Decision', 'Closing Readiness', 'Verify pre-closing conditions and disclosure timing'],
                ['2 — Decision', 'Underwriting Decision', 'Produce the final recommendation, HMDA record, and adverse action determination'],
              ].map(([wave, agent, responsibility]) => (
                <tr key={agent}>
                  <td className="px-4 py-2.5 text-xs text-slate-500">{wave}</td>
                  <td className="px-4 py-2.5 font-medium text-slate-700">{agent}</td>
                  <td className="px-4 py-2.5 text-slate-600">{responsibility}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Designed for Explainable AI</h2>
        <p>Every underwriting recommendation in Accord is fully reconstructable. For every decision, the platform preserves the exact data the AI evaluated, the rules applied, the supporting evidence, the confidence score, the regulatory citations, the human response, and every subsequent action.</p>
        <p>The result is an underwriting platform where every recommendation is transparent, reproducible, and examination-ready — from the first uploaded document to the final lending decision.</p>
      </div>
      <CTA /><Back />
    </article>
  )
}

const DOCS: Record<string, () => JSX.Element> = {
  'getting-started': DocGettingStarted,
  'data-model': DocDataModel,
  'enterprise-security': DocEnterpriseSecurity,
  'soc2-ready': DocSOC2,
  'hmda-fair-lending': DocHMDA,
  'compliant-by-design': DocCompliant,
}

export function DocPost() {
  const location = useLocation()
  const slug = location.pathname.split('/docs/')[1]?.replace(/\/$/, '')
  const Doc = slug ? DOCS[slug] : null
  if (!Doc) return <Navigate to="/docs" replace />
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <LandingNav />
      <Doc />
      <footer className="border-t border-slate-100 py-8 text-center text-sm text-slate-400">
        <Link to="/" className="hover:text-slate-600">Back to Accord</Link>
      </footer>
    </div>
  )
}

export default DocPost
