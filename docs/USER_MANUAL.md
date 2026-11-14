# User manual

## Getting started

1. Open the application URL. The home page presents the project; the **CRISP-ML** menu explains how it was built.
2. Choose **Create account**, enter a username, email and password (8+ characters, letters and numbers).
3. Log in. The **Dashboard** shows the modules available for your role.

New accounts have the **Reporter** role. Ask the administrator if you need the analyst role.

> Safety rule: never open a suspicious link to "check it". Copy it and report it.

## Reporter

### Report a suspicious URL
1. Dashboard -> **Report a suspicious URL** (or **Cases -> Report a URL**).
2. Paste the link exactly as received (it must start with `http://` or `https://`).
3. Choose where you received it (email, SMS, messaging app, social media...) and add a description.
4. Press **Send report**. The case starts with status **New**.

### Follow your reports
- **Cases** lists your reports with status and risk.
- Open a case to see the **model result** once an analyst classified it: probability, classification,
  risk level, what it means and the recommended action.
- You can edit or delete a report only while it is **New**.

### Report a wrong result or a problem
From a classified case use **Report a wrong result**, or Dashboard -> **Report a problem**.
Follow the answer in **Report a problem -> My reports**.

## Security analyst

### Classify a case
1. **Cases** -> filter by status **New**.
2. Open the case and press **Classify with the model**.
3. Read the result:
   - **Probability**: how likely the URL is phishing according to the model.
   - **Risk**: high (>= 80%), medium (above the threshold) or low.
   - **Recommended action**: high = block and escalate; medium = manual review; low = monitor.
   - **Why this result?**: the URL's features compared with typical legitimate and phishing URLs.
4. The case changes to **Classified** and its priority is set to the risk level.

### Review and close
1. Press **Take for review** (the case is assigned to you).
2. Investigate the URL safely (domain owner, age, reputation, sandbox).
3. Press **Resolve and close**: choose the verdict (phishing / legitimate) and the action
   (blocked, escalated or dismissed) and write notes. Notes are mandatory if you disagree with the model.
4. A closed case can be reopened with **Reopen case**.

### Other tools
- **Check a URL**: classify a link received outside the system and open a case from the result.
- **History**: every prediction, filterable by date, risk, result, user and model version.
- **Reports**: indicators, charts, Colombian context, and CSV export of cases and predictions.
- **Model card**: version, features and test metrics of the deployed model.

## Administrator
- **Users and roles**: filter users, change their role, deactivate accounts. You cannot remove your own admin access.
- **Monitoring**: alerts, errors, response times, drift and live model performance. Use "Exclude simulated data" for real figures.
- **Incidents and feedback**: answer user reports and mark them as resolved.

## Limitations
The model analyzes only the text of the URL; it does not visit the page. A low risk does not
guarantee that a site is safe. The analyst always makes the final decision.
