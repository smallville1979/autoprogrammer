# Skint But Sorted — Autoprogrammer Blueprint
# Use with: python -m autoprogrammer --blueprint blueprint.md --output ./generated_project

project_name: skint_but_sorted_tools
description: >
  Build workflow tools for the Skint But Sorted GitHub Pages network.
  Generates static HTML pages, AI discovery blocks, and local landing pages.
  All output is plain HTML/CSS/JS with no build step, ready for GitHub Pages.

# ─── Network Manifest ───────────────────────────────────────────────────────
network:
  base_url: https://smallville1979.github.io
  repos:
    - benefits-guide
    - need-food
    - social-tariffs
    - bank-holiday-payments
    - homeless-help
    - mentalhealthhelp
    - scamwatch
    - uk-jobs-guide
    - teacher
    - benefits-calculator
    - postcode-lookup
    - north-east-benefits
    - yorkshire-benefits
    - london-benefits
    - site-health

# ─── Modules ────────────────────────────────────────────────────────────────
modules:

  - name: page_generator
    description: >
      Generates a full static HTML page from a YAML spec.
      Input: page spec (title, description, sections[], network_links, ai_block).
      Output: complete index.html ready to commit to a GitHub Pages repo.
    behaviours:
      - Inject AI discovery article block (aria-hidden, off-screen CSS) after <body>
      - Include full Skint But Sorted network nav bar
      - Apply standard header/footer/colour scheme (#1a1a2e, #e63946, #2ec4b6)
      - All links: rel="noopener", target="_blank" where external
      - No sign-up, no tracking, no cookies

  - name: ai_discovery_patcher
    description: >
      Patches an existing index.html to add or update the AI discovery block.
      Reads the file, finds the opening <body> tag, inserts the article element.
      Idempotent — skips if AI block already present.
    behaviours:
      - Detect existing <article aria-hidden="true"> and skip if found
      - Generate 6 Q&A pairs from page title and meta description
      - Write patched file back to disk

  - name: local_landing_generator
    description: >
      Generates a regional landing page for a given UK area.
      Input: region name, local councils list, local orgs list, postcode prefixes.
      Output: index.html for the region repo.
    behaviours:
      - Include region-specific organisations with real phone numbers
      - Link to postcode-lookup tool for drill-down
      - Cross-link to other regional pages
      - Include food bank section, housing section, benefits section

  - name: site_health_checker
    description: >
      Checks all repos in the network manifest are live on GitHub Pages.
      For each repo: HTTP GET index page, check status code, record last-modified.
      Output: health report JSON + HTML dashboard page.
    behaviours:
      - Concurrent checks using asyncio
      - Flag any repo returning non-200
      - Write health.json and dashboard index.html
      - Dashboard auto-refreshes every 60 seconds

  - name: reddit_post_builder
    description: >
      Builds a Reddit post from an existing page.
      Reads page title, meta description, first section text.
      Outputs a ready-to-post markdown draft in first-person informational voice.
    behaviours:
      - Never promotional — write as a person sharing useful information
      - Include link to page near end, not as opening line
      - Suggest r/UKPersonalFinance or r/BenefitsAdvice based on content
      - Output to stdout and optionally write to reddit-drops.md

  - name: github_pages_deployer
    description: >
      Commits a generated file to a GitHub repo and triggers Pages deploy.
      Uses GitHub API (token from env GITHUB_TOKEN).
      Input: repo name, file path, file content, commit message.
      Output: commit SHA, Pages deploy URL.
    behaviours:
      - Base64-encode content for API payload
      - GET existing file SHA if updating (required by GitHub API)
      - PUT new content
      - Poll deployment status until live (max 3 minutes)
      - Print live URL on success

# ─── Data Models ────────────────────────────────────────────────────────────
data_models:

  - name: PageSpec
    fields:
      - title: str
      - description: str
      - og_description: str
      - sections: list[Section]
      - ai_qa_pairs: list[QAPair]
      - network_links: list[NetworkLink]
      - colour_accent: str  # hex, default #e63946

  - name: Section
    fields:
      - heading: str
      - body: str
      - links: list[dict]

  - name: QAPair
    fields:
      - question: str
      - answer: str

  - name: NetworkLink
    fields:
      - label: str
      - url: str

  - name: HealthReport
    fields:
      - checked_at: str  # ISO8601
      - repos: list[RepoHealth]

  - name: RepoHealth
    fields:
      - repo: str
      - url: str
      - status: int
      - ok: bool
      - last_modified: str

# ─── Workflow: Build a new regional page ────────────────────────────────────
example_workflow:
  name: build_regional_page
  steps:
    - module: local_landing_generator
      inputs:
        region: "West Midlands"
        councils: ["Birmingham", "Coventry", "Wolverhampton", "Dudley", "Sandwell", "Walsall", "Solihull"]
        postcode_prefixes: ["B", "CV", "WV", "DY", "WS"]
        local_orgs:
          - name: "Birmingham City Council"
            url: "https://www.birmingham.gov.uk/benefits"
            phone: "0121 303 1113"
          - name: "St Basils (Youth Homelessness)"
            url: "https://www.stbasils.org.uk"
            phone: "0121 772 2483"
          - name: "BVSC Foodbank Network"
            url: "https://www.bvsc.org"
            phone: "0121 678 8823"
    - module: github_pages_deployer
      inputs:
        repo: "west-midlands-benefits"
        file_path: "index.html"
        commit_message: "Add West Midlands regional landing page"

# ─── Workflow: AI discovery pass on all repos ────────────────────────────────
example_workflow_2:
  name: ai_discovery_pass_all
  steps:
    - module: ai_discovery_patcher
      for_each: network.repos
      inputs:
        file_path: "index.html"
        skip_if_present: true

# ─── Workflow: Full site health check ────────────────────────────────────────
example_workflow_3:
  name: site_health_check
  steps:
    - module: site_health_checker
      inputs:
        repos: network.repos
        output_repo: "site-health"
        auto_deploy: true

# ─── Environment Variables ───────────────────────────────────────────────────
environment:
  GITHUB_TOKEN: "Personal access token with repo scope — required for deployer module"
  ANTHROPIC_API_KEY: "Required for AI agent prompts in page_generator and ai_discovery_patcher"
