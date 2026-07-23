from .models import CompanySettings
from .permissions import access_flags


def global_context(request):
    access = access_flags(request.user) if request.user.is_authenticated else {}
    return {
        'company': CompanySettings.get_solo(),
        'access': access,
    }
