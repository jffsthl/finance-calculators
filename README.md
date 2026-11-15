# Financial Calculators

A static site of planning calculators, hosted on Azure Static Web Apps (Free tier). There is no build step: Azure serves the files as they are.

## What's here

| Calculator | File |
|---|---|
| Mortgage Payoff Planner | `calculators/mortgage-payoff.html` |
| Finance vs. Cash | `calculators/finance-vs-cash.html` |
| Future Value | `calculators/future-value.html` |
| 529 College Savings | `calculators/college-529.html` |
| Dividend Cash Flow Planner | `calculators/dividend-cash-flow.html` |
| Roth Conversion Desk | `calculators/roth-conversion.html` |
| SEP vs SIMPLE vs 401(k) | `calculators/retirement-plan-compare.html` |
| Declining Term Needs | `calculators/term-life-needs.html` |

`index.html` is the hub. It lists every calculator and opens the one you pick in the main panel. Each calculator gets its own link, e.g. `/#mortgage-payoff`, and every calculator file also works on its own.

## Adding a calculator

1. Put a self-contained HTML file in `calculators/`, for example `calculators/my-tool.html`.
2. In `index.html`, add a row to the `CALCS` list with `id: "my-tool"`, a title and a one-line description.
3. Commit and push. Azure redeploys automatically.

## Deploying to Azure (one time)

1. In the Azure portal, choose **Create a resource → Static Web App**.
2. **Plan type:** Free. **Source:** GitHub. Sign in, then pick this repo and the `main` branch.
3. **Build presets:** Custom. **App location:** `/`. Leave **Api location** and **Output location** blank.
4. Click **Create**. Azure adds a workflow file under `.github/workflows/` to this repo and runs the first deploy. Your URL is on the resource's **Overview** page.

After that, every push to `main` redeploys the site.

## Notes

- The site is public but hidden from search engines (`robots.txt`, `noindex` tags, and an `X-Robots-Tag` header).
- Inputs are saved in each visitor's browser (`localStorage`). Nothing is sent to a server.
- External dependencies are Google Fonts and Chart.js from cdnjs.
- The Dividend Cash Flow Planner's live ticker lookup only works inside the Claude desktop app, so the hosted copy hides those buttons. Yields and growth rates are entered by hand.
