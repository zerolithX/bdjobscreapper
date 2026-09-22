# BD Job Notification

A GitHub-ready Bangladesh job aggregator with a lightweight static frontend and scheduled Python scraper.

## Sources
- BD Govt Job — https://bdgovtjob.net/
- The CV Guy — https://thecvguy.net/jobs-and-careertips/

The app stores structured job metadata in `data/jobs.json`. The scraper does not bypass CAPTCHA, login, access controls, or robots restrictions. Review each source's robots.txt and terms before running it frequently.

## Run locally
```bash
pip install -r requirements.txt
python scraper/scrape_sources.py
python -m http.server 8080
```
Open `http://localhost:8080`.

## GitHub Pages
Push the repository to GitHub and enable Pages from the `main` branch root. The workflow updates `data/jobs.json` every 6 hours.

## Important
The frontend is an original UI and does not copy the source sites' branding or page layout. It links users to the original source/application pages.
