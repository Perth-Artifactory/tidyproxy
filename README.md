# Tidyproxy

We have a number of different tools that need independent access to TidyHQ, in particular since it's use as an account mapper has increased. Unfortunately the response time for TidyHQ queries, especially the large queries required for mapping, push us over the allowable response time for things like Slack triggers.

Rather than relying on live processing of queries the goal is to have everything pre-indexed/generated and serve it directly through a more performant front end like NGINX.

## Setup

Files are dumped into `/serve`. Serving and securing the data is left up to the user.

## Data

### Raw/Backwards Compatible

`cache.json`

This includes the information currently retrieved within other applications and can be used as a direct stand in.

* **Contacts**: A list of all contacts.
* **Groups**: A dictionary of groups indexed by ID.
* **Memberships**: A list of all memberships.
* **Invoices**: A dictionary of invoices indexed by contact ID.
* **Organization Details**: Information about the organization.

### Contacts

* A dictionary of contacts indexed by ID: `contacts/sorted.json`.
* Individual contact files: `contacts/{ID}.json`.

### Groups

Each group includes a "membership" key listing the IDs of contacts that are members.

* A dictionary of groups indexed by group ID: `groups/sorted.json`.
* Individual group files: `groups/{GROUP_ID}.json`.

### Invoices

* A dictionary of invoices indexed by contact ID: `invoices/sorted.json`.
* Individual invoice files: `invoices/{ID}.json`.
* A dictionary of all invoices indexed by invoice ID: `invoices/all_sorted.json`. This is provided sorted but may become unsorted depending on how the file is processed.
* A list of all invoices sorted by date: `invoices/all.json`.

### Memberships

* A dictionary of memberships indexed by contact ID: `memberships/sorted_by_contact.json`.
* A dictionary of memberships indexed by membership type ID: `memberships/sorted_by_type.json`.
* Individual membership files: `memberships/{CONTACT_ID}.json`.

### Account Mapping

Contact maps are provided in multiple formats indexed by the user ID of each service. Each map includes an explicit map to every other service (null if no account).

Since this data is sourced **purely** from TidyHQ it will not include Slack/Taiga accounts with no associated TidyHQ account.

* Slack: `map/slack.json`, `map/slack/{SLACK_ID}.json`
* Taiga: `map/taiga.json`, `map/taiga/{TAIGA_ID}.json`
* TidyHQ: `map/tidyhq.json`, `map/tidyhq/{TIDYHQ_ID}.json`

### Org details

* Org details (domain prefix etc): `org.json`
