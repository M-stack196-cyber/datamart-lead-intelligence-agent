"""Conservative, attributed ICP hypotheses from supplied Vibe data, not new facts."""
from dataclasses import asdict, dataclass
import re
from typing import Any

from app.services.vibe_identity import company_host, normalized_name, normalized_url

# User-supplied domain/category examples are inference hints, not an allowlist.
# No domain hint establishes headcount, revenue, ownership, or qualification.
DOMAIN_HINTS = {
    'openrouter.ai': ('SaaS/AI software', 20, 10),
    'taskade.com': ('SaaS/productivity software', 20, 10),
    'tryatria.com': ('SaaS/AI software', 20, 10),
    'syllaby.ai': ('SaaS/AI software', 20, 10),
    'qubrid.com': ('AI/cloud/software', 20, 10),
    'securestrux.com': ('Cybersecurity/compliance', 15, 5),
    'gaiare.com': ('Real Estate / PropTech potential', 15, 0),
    'pocketpatientmd.com': ('HealthTech', 20, 10),
    'plannerly.com': ('Construction/BIM software', 20, 10),
    'experfy.com': ('Analytics/AI/talent platform', 20, 5),

    # Latest production examples from Vibe discovery.
    # These are still hypotheses only; they do not prove size, revenue, ownership, or qualification.
    'mem0.ai': ('SaaS/AI software', 20, 10),
    'julius.ai': ('SaaS/AI software', 20, 10),
    'b2metric.com': ('Analytics/MarTech/data platform', 20, 10),
    'hellopatient.com': ('HealthTech', 20, 10),
    'fintechamericas.co': ('FinTech/financial software', 20, 5),
    'fuelfinance.me': ('FinTech/financial software', 20, 5),
    'pocus.com': ('Analytics/MarTech/data platform', 20, 10),
    'corvee.com': ('FinTech/financial software', 15, 5),
    'itracusa.com': ('SaaS/software platform', 15, 5),
}
CATEGORY_TERMS = (
    ('HealthTech', ('healthtech', 'healthcare software', 'patient platform', 'clinical software', 'electronic health records')),
    ('FinTech/financial software', ('fintech', 'financial software', 'payments platform', 'banking software')),
    ('Real Estate / PropTech potential', ('real estate', 'proptech', 'property technology', 'property management software')),
    ('E-commerce/DTC', ('e-commerce', 'ecommerce', 'dtc', 'commerce platform')),
    ('Analytics/MarTech/data platforms', ('analytics', 'martech', 'data platform', 'data engineering', 'business intelligence')),
    ('Cybersecurity/compliance', ('cybersecurity', 'cyber security', 'compliance software', 'security software', 'cmmc')),
    ('Construction/BIM software', ('construction tech', 'construction software', 'bim', 'building information modeling', 'workflow software')),
    ('SaaS/AI software', ('saas', 'software', 'artificial intelligence', 'ai', 'cloud', 'productivity software', 'machine learning')),
)
SOFTWARE_TERMS = ('saas', 'software', 'artificial intelligence', 'ai', 'cloud', 'bim',
                  'platform', 'data engineering', 'cybersecurity', 'healthtech', 'fintech', 'proptech')

GENERIC_DOMAIN_HINTS = (
    ('SaaS/AI software',
     ('ai', 'cloud', 'automation', 'platform', 'software', 'app', 'apps', 'tech', 'labs'),
     20, 10),
    ('FinTech/financial software',
     ('fintech', 'finance', 'wealth', 'pay', 'payments', 'bank', 'tax', 'accounting', 'invoice', 'billing'),
     20, 5),
    ('HealthTech',
     ('patient', 'health', 'healthcare', 'care', 'clinic', 'medical', 'med', 'md', 'pharma'),
     20, 10),
    ('Analytics/MarTech/data platform',
     ('metric', 'analytics', 'data', 'cdp', 'insight', 'predictive', 'intelligence', 'pocus'),
     20, 10),
    ('MarTech/SaaS',
     ('crm', 'sales', 'growth', 'marketing automation', 'customer success', 'customer'),
     15, 5),
    ('Real Estate / PropTech potential',
     ('real estate', 'property', 'proptech', 'realtor', 'brokerage'),
     15, 0),
)


def _matches(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text.casefold()) for term in terms)


def raw_layers(prospect: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    layers = [('', prospect)]
    # Stored ingest envelopes can contain the adapter's own raw_source_data.
    for _ in range(3):
        path, row = layers[-1]
        raw = row.get('raw_source_data')
        if not isinstance(raw, dict):
            break
        layers.append((path + 'raw_source_data.', raw))
    return layers


def prepare_vibe_prospect(prospect: dict[str, Any]) -> dict[str, Any]:
    """Fill actual provider attributes only. Never replace facts with hypotheses."""
    result = dict(prospect)
    aliases = {
        'company_url': ('company_url', 'company_website'),
        'company_linkedin_url': ('company_linkedin_url', 'company_linkedin'),
        'company_description': ('company_description',),
        'description': ('description',),
    }
    for target, sources in aliases.items():
        if isinstance(result.get(target), str) and result[target].strip():
            continue
        for _, layer in raw_layers(prospect):
            value = next((layer.get(key) for key in sources
                          if isinstance(layer.get(key), str) and layer[key].strip()), None)
            if value:
                result[target] = value
                break
    return result


def _texts(value: Any, depth: int = 0) -> list[str]:
    """Read known text leaves, not arbitrary metadata keys or unbounded payloads."""
    if depth > 4:
        return []
    if isinstance(value, str):
        return [value[:2000]] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value[:50] for text in _texts(item, depth + 1)]
    if isinstance(value, dict):
        return [text for key in ('name', 'skill', 'skill_name', 'title', 'description', 'summary', 'value')
                for text in _texts(value.get(key), depth + 1)]
    return []


@dataclass(frozen=True)
class InferredIcpSignals:
    industries: list[str]
    industry_points: int
    software_points: int
    sources: list[dict[str, str]]

    def payload(self) -> dict[str, Any]:
        return {'inferred': True, **asdict(self)}


def infer_icp_signals(prospect: dict[str, Any]) -> InferredIcpSignals:
    prospect = prepare_vibe_prospect(prospect)
    host = company_host(prospect.get('company_url'))
    source_url = str(prospect.get('company_url') or '').strip()
    if source_url and '://' not in source_url:
        source_url = 'https://' + source_url
    name = normalized_name(prospect.get('company_name'))
    company_linkedin = str(prospect.get('company_linkedin_url') or '')
    industries: list[str] = []
    sources: list[dict[str, str]] = []
    industry_points = software_points = 0

    def record(field: str, category: str, industry: int, software: int) -> None:
        nonlocal industry_points, software_points
        if category not in industries:
            industries.append(category)
        industry_points = max(industry_points, industry)
        software_points = max(software_points, software)
        source = {'field': field, 'signal': category,
                  'source_url': source_url}
        if source not in sources:
            sources.append(source)

    for domain, (category, points, software) in DOMAIN_HINTS.items():
        if host == domain or host.endswith('.' + domain):
            record('company_url (user-supplied domain hypothesis)', category, points, software)

    # Conservative broad inference from current company name and title.
    # Do not infer from a bare .ai TLD, URL path, or spoofed host like openrouter.ai.evil.example.
    # Fixed known domains are handled by DOMAIN_HINTS above.
    broad_signal_text = ' '.join([
        str(prospect.get('company_name') or ''),
        str(prospect.get('title') or ''),
    ]).casefold()

    for category, terms, points, software in GENERIC_DOMAIN_HINTS:
        if _matches(broad_signal_text, terms):
            record('company_name/title hypothesis', category, points, software)

    company_context: list[tuple[str, str]] = []
    personal_context: list[tuple[str, str]] = []
    for path, row in raw_layers(prospect):
        for key in ('company_name', 'company_description', 'description', 'industry', 'business_model'):
            company_context.extend((path + key, text) for text in _texts(row.get(key)))
        for key in ('title', 'skills', 'job_level_array', 'job_seniority_level', 'job_department_array'):
            personal_context.extend((path + key, text) for text in _texts(row.get(key)))
        experience = row.get('experience')
        if isinstance(experience, list):
            for index, job in enumerate(experience[:50]):
                if not isinstance(job, dict):
                    continue
                employer = job.get('company_name') or job.get('company')
                employer = employer.get('name') if isinstance(employer, dict) else employer
                job_host = company_host(job.get('company_website') or job.get('company_url'))
                job_linkedin = job.get('company_linkedin')
                # Previous/unattributed jobs must not become current-company facts.
                if job.get('end_date') or job.get('is_current') is False or job.get('current') is False:
                    continue
                same_company = (bool(name) and normalized_name(employer) == name) or (bool(host) and job_host == host)
                same_company = same_company or (bool(company_linkedin) and normalized_url(job_linkedin) == normalized_url(company_linkedin))
                if not same_company:
                    continue
                for key in ('title', 'description', 'summary', 'company_description'):
                    for text in _texts(job.get(key)):
                        company_context.append((f'{path}experience[{index}].{key}', text))

    # URL host words can corroborate a company signal; a .ai suffix alone cannot.
    company_context.append(('company_url host', re.sub(r'[._-]+', ' ', host.split('.', 1)[0])))
    for field, text in company_context:
        for category, terms in CATEGORY_TERMS:
            if _matches(text, terms):
                # Real-estate activity alone is not evidence of a software product.
                software = 5 if _matches(text, SOFTWARE_TERMS) else 0
                strong = _matches(text, ('saas', 'software', 'platform', 'healthtech', 'fintech', 'bim'))
                record(field, category, 20 if strong else 15,
                       10 if strong and software and not field.endswith(('industry', 'business_model')) else software)

    # Explicit product/vertical terms in a buyer title support a hypothesis;
    # a generic CEO/Founder/CTO label does not establish an industry.
    for field, text in personal_context:
        if field.endswith('title'):
            for category, terms in CATEGORY_TERMS:
                if _matches(text, terms):
                    record(field, category, 15, 5 if _matches(text, SOFTWARE_TERMS) else 0)

    # A technical role plus a specific relevant skill supports a moderate
    # hypothesis when company text is sparse. Either signal alone is insufficient.
    technical_role = any(
        _matches(text, ('cto', 'engineering', 'information technology', 'product development'))
        for field, text in personal_context if not field.endswith('skills')
    )
    if not industries and technical_role:
        for field, text in personal_context:
            if field.endswith('skills'):
                for category, terms in CATEGORY_TERMS:
                    if _matches(text, terms):
                        record(field, category, 15, 5)

    # Skills and role metadata are personal context, not company industry facts.
    # Require an independently identified company category before adding points.
    if industries:
        for field, text in personal_context:
            if _matches(text, SOFTWARE_TERMS + ('engineering', 'information technology', 'product development')):
                record(field, industries[0], 0, 5)
    if industries:
        for field, text in personal_context:
            if any(field.endswith(key) for key in ('job_level_array', 'job_seniority_level')):
                if _matches(text, ('founder', 'c-suite', 'executive', 'owner', 'director')):
                    source = {'field': field, 'signal': 'Role seniority context (no additional points)',
                              'source_url': source_url}
                    if source not in sources:
                        sources.append(source)
    return InferredIcpSignals(industries, industry_points, software_points, sources)
