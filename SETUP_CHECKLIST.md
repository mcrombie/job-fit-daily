# Setup checklist

- [ ] Open the synthetic preview with `scripts\preview.ps1`.
- [ ] Read `config/profile.json` and adjust salary, target roles, and blocked terms.
- [ ] Create `mcrombie/job-fit-daily` on GitHub.
- [ ] Initialize Git, commit, and push to `main`.
- [ ] Set **Settings → Pages → Source** to **GitHub Actions**.
- [ ] Manually run **Daily Job Fits** once without email.
- [ ] Confirm that the Pages dashboard loads and contains live rather than demonstration jobs.
- [ ] Add a `DASHBOARD_URL` Actions variable.
- [ ] Add SMTP secrets only after the dashboard is working.
- [ ] Optionally enable USAJOBS and add its credentials.
- [ ] Add selected Greenhouse and Lever employer-board tokens over time.
- [ ] Review the source-health panel after the first scheduled 8:17 a.m. run.
