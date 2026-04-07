# Privacy Policy

**Effective Date:** April 3, 2026
**Last Updated:** April 3, 2026

This Privacy Policy describes how Joel Libni ("we", "us", "the Operator"), operating deepmiro.org ("the Service"), collects, uses, and protects your personal information.

---

## 1. What We Collect

### Information you provide
- **Account information** — email address, password (hashed), display name
- **Simulation inputs** — prompts, uploaded files (PDF, Markdown, TXT), and configuration parameters you submit for simulations
- **Payment information** — processed entirely by LemonSqueezy; we do not store credit card numbers or bank details

### Information collected automatically
- **Usage data** — simulation count, timestamps, tier usage, API request logs
- **Technical data** — IP address, MCP client type, request headers
- **Cloudflare data** — standard web traffic metadata (see Cloudflare's privacy policy)

### Information we do NOT collect
- We do not use analytics or tracking tools (no Google Analytics, no tracking pixels)
- We do not use advertising cookies
- We do not collect biometric data or precise location data

---

## 2. How We Use Your Data

| Data | Purpose | Legal Basis (GDPR) |
|------|---------|-------------------|
| Email, password | Account authentication | Contract performance |
| Simulation inputs | Running your simulations | Contract performance |
| Simulation outputs | Delivering results to you | Contract performance |
| Usage data | Enforcing tier limits, abuse prevention | Legitimate interest |
| Technical data | Security, debugging, infrastructure | Legitimate interest |
| Payment data | Billing (via LemonSqueezy) | Contract performance |

We do **not** use your simulation data to train AI models, sell to third parties, or for any purpose beyond providing the Service.

---

## 3. Third-Party Data Processors

Your data is processed by these third-party services as necessary to operate the Service:

| Service | What they process | Their privacy policy |
|---------|------------------|---------------------|
| **Fireworks AI** | Simulation prompts and text content (sent for LLM inference) | [fireworks.ai/privacy](https://fireworks.ai/privacy) |
| **LemonSqueezy** | Payment and billing data | [lemonsqueezy.com/privacy](https://www.lemonsqueezy.com/privacy) |
| **Cloudflare** | Web traffic, IP addresses, DNS | [cloudflare.com/privacy](https://www.cloudflare.com/privacypolicy/) |
| **Contabo** | All data (hosting provider, EU datacenter) | [contabo.com/privacy](https://contabo.com/en/privacy/) |

**Important:** When you run a simulation, your input text is sent to Fireworks AI's API for LLM processing. Fireworks AI processes this data according to their privacy policy and data processing terms. We use their API tier that does not retain prompts for training.

---

## 4. Where Your Data Is Stored

- **Primary hosting:** Contabo datacenter in the European Union (Germany)
- **CDN/proxy:** Cloudflare (global edge network)
- **LLM processing:** Fireworks AI (United States)
- **Payments:** LemonSqueezy (United States)

Your simulation data at rest is stored on EU-based servers. However, simulation text is transmitted to US-based LLM providers for processing during active simulations.

---

## 5. Data Retention

| Data | Retention period |
|------|-----------------|
| Account information | Until you delete your account |
| Simulation data | 90 days after creation, or until you delete it |
| Usage logs | 90 days |
| Technical/security logs | 30 days |
| Payment records | As required by tax law (typically 7 years, held by LemonSqueezy) |

After account deletion, all associated data is permanently removed within 30 days.

Inactive Free tier accounts may be deleted after 12 months with 30 days' email notice.

---

## 6. Your Rights

If you are in the EU/EEA, you have the following rights under GDPR:

- **Access** — request a copy of your personal data
- **Rectification** — correct inaccurate data
- **Erasure** — request deletion of your data ("right to be forgotten")
- **Portability** — receive your data in a machine-readable format
- **Restriction** — limit how we process your data
- **Objection** — object to processing based on legitimate interest
- **Withdraw consent** — where processing is based on consent

To exercise any of these rights, contact us at kakarot.joel@gmail.com. We will respond within 30 days.

Regardless of your location, you can:
- Delete your account and all associated data at any time
- Export your simulation data via the API
- Revoke and regenerate API keys

---

## 7. Data Security

We implement reasonable security measures including:
- Passwords are hashed (never stored in plaintext)
- API keys are generated with sufficient entropy
- All traffic is encrypted via HTTPS (Cloudflare SSL)
- Server access is restricted (SSH key authentication, Tailscale private network)
- No unnecessary data collection

We are a solo-operated service. While we take security seriously, we cannot guarantee absolute security. If we discover a data breach affecting your personal data, we will notify you via email within 72 hours.

---

## 8. Children

The Service is not intended for users under 18 years of age. We do not knowingly collect data from minors. If you believe a minor has provided us with personal data, contact us and we will delete it.

---

## 9. Cookies

Our use of cookies is minimal and described in our [Cookie Policy](/docs/legal/cookie-policy).

---

## 10. Changes to This Policy

We may update this Privacy Policy at any time. Material changes will be communicated via email at least 14 days before they take effect. The "Last Updated" date at the top of this page will reflect the most recent revision.

---

## 11. Contact

For privacy-related questions or requests:

**Email:** kakarot.joel@gmail.com
**GitHub:** [github.com/kakarot-dev/deepmiro](https://github.com/kakarot-dev/deepmiro)

If you are in the EU and believe your data protection rights have been violated, you have the right to lodge a complaint with your local data protection authority.
