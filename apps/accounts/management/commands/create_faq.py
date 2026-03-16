from django.core.management.base import BaseCommand
from apps.accounts.models import FAQ


class Command(BaseCommand):
    help = 'Создание примеров FAQ для проекта AutoHandy'

    def handle(self, *args, **kwargs):
        faqs_data = [
            {
                'question': 'Как зарегистрироваться в системе AutoHandy?',
                'answer': 'Для регистрации в системе AutoHandy просто войдите через кнопку "Вход" и введите ваш номер телефона или email. Вам придет 4-значный код подтверждения. После ввода кода вы автоматически будете зарегистрированы. При регистрации выберите вашу роль: Водитель (Driver) или Мастер (Master).',
                'order': 1
            },
            {
                'question': 'Как мастеру начать принимать заказы?',
                'answer': 'Для начала работы мастером необходимо: 1) Зарегистрироваться с ролью "Master", 2) Заполнить профиль с указанием своих услуг и местоположения, 3) Убедиться, что ваш баланс положительный (минимум 1000 ₽ для активации профиля), 4) После этого водители смогут видеть вас в списке мастеров и создавать заказы.',
                'order': 2
            },
            {
                'question': 'Как водителю найти мастера и создать заказ?',
                'answer': 'В разделе "Мастера" вы можете просмотреть список доступных мастеров в вашем городе или рядом с вашим местоположением. Выберите нужного мастера, посмотрите его услуги и рейтинг. Затем создайте заказ, указав вашу машину, описание проблемы и желаемое время. Мастер получит уведомление о вашем заказе.',
                'order': 3
            },
            {
                'question': 'Как пополнить баланс в системе?',
                'answer': 'Пополнение баланса доступно для всех пользователей. Перейдите в раздел "Профиль" -> "Баланс" и выберите удобный способ пополнения. Минимальная сумма пополнения - 200 ₽. Мастерам требуется минимум 1000 ₽ на балансе для активации профиля и приема заказов.',
                'order': 4
            },
            {
                'question': 'Какие услуги доступны в AutoHandy?',
                'answer': 'В AutoHandy доступны различные услуги по обслуживанию автомобилей: диагностика, ремонт двигателя, замена масла, шиномонтаж, развал-схождение, кузовной ремонт, электрика, компьютерная диагностика и многое другое. Каждый мастер указывает список своих услуг в профиле.',
                'order': 5
            }
        ]

        created_count = 0
        updated_count = 0

        for faq_data in faqs_data:
            faq, created = FAQ.objects.update_or_create(
                question=faq_data['question'],
                defaults={
                    'answer': faq_data['answer'],
                    'order': faq_data['order'],
                    'is_active': True
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Создан FAQ: {faq_data["question"][:50]}...')
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f'↻ Обновлен FAQ: {faq_data["question"][:50]}...')
                )

        self.stdout.write(
            self.style.SUCCESS(f'\n✓ Успешно создано FAQ: {created_count}')
        )
        self.stdout.write(
            self.style.SUCCESS(f'✓ Успешно обновлено FAQ: {updated_count}')
        )
        self.stdout.write(
            self.style.SUCCESS(f'✓ Всего FAQ в системе: {FAQ.objects.count()}')
        )

