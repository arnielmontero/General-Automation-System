def access(request):
    """``modules``: module codes the logged-in user may use, for showing / hiding menus and buttons."""
    user = getattr(request, "user", None)
    return {"modules": user.modules if user is not None and user.is_authenticated else frozenset()}
