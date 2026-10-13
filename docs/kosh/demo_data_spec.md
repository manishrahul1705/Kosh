# Kosh demo data specification

The deterministic seed 42 dataset represents the fictional Bengaluru CNC job shop Meenakshi Precision Components from January 2024 through October 2026. Currency values are written as decimal INR text and become integer paise at intake.

Twelve fictional customers receive one invoice per month. Their nominal payment delays in days are: ABC Industries 52, Deccan Heavy Machines Ltd (CPSE) 34, Aranya Motion Works 38, Bluepeak Foundry 45, Cauvery Tooling House 31, Dakshin Drives 42, Evergreen Process Systems 36, Frontier Fabrication 48, Granite Industrial Works 40, Horizon Mechatronics 33, Indus Valley Components 46 and Jasmine Engineering Works 29. A seeded uniform variation of plus or minus seven days applies. ABC Industries receives a further 12-day delay from July 2026. The Deccan customer is marked CPSE and TReDS-onboarded during seeding.

Four fictional suppliers receive monthly purchases. Settled sales and purchases have paid dates and corresponding bank entries. Recent invoices remain open. The bank account is masked to its last four digits and begins at INR 95,000. Monthly payroll, rent, equipment EMI, GST and TDS obligations create a plausible liquidity pressure five to seven weeks after 13 October 2026 when realistic collection delays are applied.

Fourteen native-text customer invoices mirror open receivables. One supplier invoice contains otherwise legitimate fields plus tiny instruction-like payment text. Intake must keep the legitimate invoice evidence while marking that document for review.
