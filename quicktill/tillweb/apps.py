from django.apps import AppConfig


class TillWebConfig(AppConfig):
    name = 'quicktill.tillweb'
    verbose_name = "Till web interface"

    def ready(self):
        self.Till = self.get_model("Till")

    def get_sidebar(self, user):
        tills = self.Till.objects.filter(access__user=user).order_by('name')
        if len(tills) > 0:
            return [{'name': "Till access",
                     'objects': tills}]
        return []
