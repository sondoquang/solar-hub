import factory

from apps.domains.models import DomainInfo
from apps.sites.tests.factories import SiteFactory


class DomainInfoFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DomainInfo

    site = factory.SubFactory(SiteFactory)
    host = factory.LazyAttribute(lambda o: o.site.base_url.split("//")[1])
    domain = "example.com"
    whois_status = DomainInfo.CheckStatus.OK
    dns_status = DomainInfo.CheckStatus.OK
    ssl_status = DomainInfo.CheckStatus.OK
    blacklist_status = DomainInfo.CheckStatus.OK
    blacklist_verdict = DomainInfo.BlacklistVerdict.CLEAN
    gindex_status = DomainInfo.CheckStatus.SKIPPED
