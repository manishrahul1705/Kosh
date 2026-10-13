# Project demo guide

This is a local GeM Tender Intelligence & Seller Matching demonstration. AI is optional and disabled in this demo. The source database and verified public documents are copied; only the disposable copy is reduced to three real packages and one labelled fixture.

## Start the backend

```powershell
Set-Location 'C:\Users\Manish\Downloads\Gem-Final\gem-tender-intelligence'
$demoPython = 'C:\Users\Manish\Downloads\gem-tender-intelligence-stage4-complete\.venv\Scripts\python.exe'
& $demoPython scripts/run_project_demo.py --prepare-only
& $demoPython scripts/run_project_demo.py
```

The server binds to 127.0.0.1:8000. Scheduling, startup recovery, migration, acquisition and broad workers are disabled. Its AI key is empty; no provider is called. The initial snapshot must exist at `validation/balanced-input/staging.db` with its documents; it is available in this verified workspace. Restarting preserves the demo. To create another untouched demo, use `--output validation/another-demo` on both commands.

## Start the frontend

In a second terminal:

```powershell
Set-Location 'C:\Users\Manish\Downloads\Gem-Final\gem-tender-intelligence\frontend'
$env:VITE_DEV_LOGIN = 'true'
npm.cmd run dev -- --host 127.0.0.1
```

Open **http://localhost:5173**. Sign in with **demo@gem.local**; this local development flow needs no password/Supabase account. Tokens are process-local and normal seller membership authorization still applies. The production frontend build does not permit this development login.

## Five profiles

Use the **Active seller** selector. Names start with DEMO and their attributes/documents are synthetic demonstration claims, not verified businesses.

- Strong: high turnover and experience.
- Low turnover: turnover 1 and zero experience.
- Incomplete: turnover and experience absent.
- MSE: strong numeric profile with explicit MSE status.
- Startup: strong numeric profile with explicit startup status.

Flags do not independently grant a tender exemption. The same real package can produce different outcomes; documentary requirements can keep a strong profile in review.

## Real packages

Search one of these exact bid numbers in My Tenders:

| Real tender | Subject | Package | Demo purpose |
|---|---|---|---|
| GEM/2026/B/8132740 | Nvivo-15 Perpetual License | Complete | Low seller's numeric failures versus other sellers' review reasons; specification and source evidence |
| GEM/2026/B/8143665 | Tapping screws | Complete | Native main PDF and logical static catalogue requirements |
| GEM/2026/B/8145831 | Rod DIA16MM | Complete | Main/specification PDFs and documentary review |

These are previously verified live records with original source status/dates intact; no deadline was changed to make the demo work. They are a dated snapshot, not a forever-live seed. After their real deadlines, closed filtering correctly removes them from active opportunities. Refresh actual GeM status before any later presentation requiring a live claim.

## All three match states

Use **DEMO/FIXTURE/001**, whose title and PDF both say it is not a real GeM tender. The generated PDF is actually extracted, structured and evaluated by the services; match states are not inserted manually.

| Profile | Fixture outcome |
|---|---|
| Strong / MSE / Startup | Matched |
| Low turnover | Not matched |
| Incomplete | Needs review |

Its one known mandatory threshold is 7 lakh annual turnover. This fixture proves the comparison flow, not eligibility for an actual company or all free-form clauses.

## Five-minute presentation

1. Sign in and show the overview counts, product profile link and Refresh matches.
2. Choose DEMO Strong Seller; search Nvivo and open its COMPLETE package.
3. Show main/specification documents, native extraction labels and authenticated download.
4. Show structured tender details and eligibility. Read one source quote with its document/page citation.
5. Show Your match: explain why documentary information still needs review.
6. Return to My Tenders, switch to Low turnover, select Not matched and show Nvivo's explicit failures.
7. Switch to Incomplete: missing turnover/experience produces review, not automatic rejection.
8. Show the clearly labelled fixture to demonstrate Matched for Strong versus the other two states.
9. Open Seller Profile. A save creates a new revision and requests matching. Multiple quick saves may trigger the 30-second refresh cooldown; the profile is still saved. Wait, then use Refresh matches.
10. Sign out. Explain that source-backed deterministic evaluation works without optional summaries.

## Stop or validate

Use Ctrl+C in the two task-owned terminals, or stop the backend gracefully:

```powershell
Set-Location 'C:\Users\Manish\Downloads\Gem-Final\gem-tender-intelligence'
New-Item -ItemType File -Path validation/project-demo-final/STOP -Force | Out-Null
```

The launcher removes only its own STOP marker on restart. It never kills other Python/Node processes. Rendered React integration and a local snapshot demo are distinct from live browser authentication or current source availability.
