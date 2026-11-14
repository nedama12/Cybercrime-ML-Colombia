# Training guide (30-minute session)

Goal: after the session each participant can report a URL, an analyst can take a case from
report to closure, and the administrator can read the monitoring dashboard.

Preparation: deployed application, one account per role, simulated data loaded with
`flask --app app seed-demo` (records are labeled SIMULATED).

| Time | Topic | Demonstration | Participants do |
|---|---|---|---|
| 0-5 min | Why the system exists | Home page and CRISP-ML phase 1 | - |
| 5-10 min | Reporter | Create account, report a URL, follow its status | Report one of the example links below |
| 10-20 min | Analyst | Classify, interpret probability, risk and recommendation, take for review, close with a verdict | Close one case agreeing and one disagreeing with the model (with notes) |
| 20-25 min | Reports and history | Filters, charts, CSV export, model card | Export the cases CSV |
| 25-30 min | Administrator and support | Roles, monitoring alerts, incident answer | Send one "Report a problem" |

Example links for the exercise (fictitious, do not open):
- `http://bancolombia-verificacion-cuenta.weebly.com/login.php`
- `https://dian-devolucion-saldo.xyz/formulario?id=88231`
- `https://www.unal.edu.co`

Key messages:
1. Never open a suspicious link; copy and report it.
2. The model prioritizes, the analyst decides.
3. Every verdict improves the next version of the model.
4. Wrong results and errors are reported from the application.

Check of understanding: each participant explains what "medium risk" means and which action
corresponds to a confirmed phishing URL.
