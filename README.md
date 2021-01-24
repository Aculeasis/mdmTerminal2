# mdmTerminal 2
[![Build status](https://ci.appveyor.com/api/projects/status/v98bcj9mr2s1g13a/branch/master?svg=true)](https://ci.appveyor.com/project/Aculeasis/mdmterminal2)

Голосовой терминал для домашней автоматизации, форк [mdmPiTerminal](https://github.com/devoff/mdmPiTerminal).

**Возможности**
- Запуск распознавания по любым ключевым словам.
- Передача команд на сервер.
- Поддержка [MajorDroid API](https://mjdm.ru/forum/viewtopic.php?f=5&t=518) (sayReply, ask etc.).
- [Отправка уведомлений](https://github.com/Aculeasis/mdmTerminal2/wiki/callback) на сервер.
- [Работа через прокси](https://github.com/Aculeasis/mdmTerminal2/wiki/proxy).
- [Модули](https://github.com/Aculeasis/mdmTerminal2/wiki/modules).
- [Плагины](https://github.com/Aculeasis/mdmTerminal2/wiki/plugins).

**Интеграция**
- [MajorDoMo](https://github.com/sergejey/majordomo): [MDM VoiceAssistant](https://github.com/lanket/mdmPiTerminalModule).
- [intraHouse](https://github.com/intrahouseio): [plugin-voiceterminal](https://github.com/intrahouseio/intraHouse.plugin-voiceterminal) (WIP).
- [Home Assistant](https://home-assistant.io/): Через [плагин](https://github.com/netman1ac/mdmt2-mqtt) для поддержки MQTT.
- [Приложение под Android](https://github.com/Aculeasis/mdmt2-config-android).
- Google Home: Через [плагин](https://github.com/Aculeasis/mdmt2-google-assistant) (частично).
- [API документация](https://github.com/Aculeasis/mdmTerminal2/wiki/API-(draft)) (WIP).

# Установка
**Используя докер**: [Dockerfile и готовые образы под x86_64, aarch64, armv7l](https://github.com/Aculeasis/mdmt2-docker)

## Обычная установка
### Подготовка
- Проверка работы записи\воспроизведения

  Запустите `arecord -d 5 -f S16_LE -r 16000 __.wav && aplay __.wav && rm __.wav` и говорите что-нибудь 5 секунд.

Вы должны услышать запись своего голоса. Если что-то пошло не так аудиосистема требует настройки.

Скопируйте один из файлов из `mdmTerminal2/asound` в `/etc/asound.conf`. Для OPi zero +2 H5 должен подойти `asound_h3.conf
`
#### Armbian на OrangePi
- Аналоговые кодеки:

  Запустите `armbian-config` -> System -> Hardware. Включите *analog-codec* и перезагрузите апельсинку.
- Встроенный микрофон (проверял на Zero +2 H5 с платой):

  `alsamixer` -> F4 выбираем Mic1 и жмем space, выходим

Узнайте на каком устройстве находятся микрофон и динамик через команды:
```bash
    aplay -l
    arecord -l
```
и отредактировать если нужно `"hw:X,0"` в `/etc/asound.conf`

Если запись или воспроизведение все еще не работают, можно поискать решение [на форуме](https://mjdm.ru/forum/viewtopic.php?f=5&t=5460)

### Установка
Клонируйте репозиторий и запустите скрипт установки:
```bash
    cd ~/
    git clone https://github.com/Aculeasis/mdmTerminal2
    cd mdmTerminal2
    ./scripts/install.sh
```

Теперь можно запустить терминал в консоли и проверить его работоспособность:
```bash
    ./run.sh
```
Если все работает можно добавить сервис в systemd - терминал будет запускаться автоматически:
```bash
    ./scripts/systemd_install.sh
```
И посмотреть статус сервиса:
```bash
    sudo systemctl status mdmterminal2.service
```

### Удаление
Удалить сервис и директорию терминала, все данные и настройки будут также удалены:
```bash
cd ~/
./mdmTerminal2/scripts/systemd_remove.sh
rm -rf mdmTerminal2/
```

# Настройка
### [Описание всех настроек](https://github.com/Aculeasis/mdmTerminal2/wiki/settings.ini)
**Важно!** Значительная часть настроек не доступна через MDM VoiceAssistant, их можно изменить отредактировав `mdmTerminal2/src/settings.ini` или
установить плагин [web-config](https://github.com/Aculeasis/mdmt2-web-config) и настроить все в браузере.

[Настройка системных фраз](https://github.com/Aculeasis/mdmTerminal2/wiki/phrases.json)

## Подключение к MajorDoMo
**Создание терминала**:
- После заходим - в Настройки > Терминалы > Добавить новую запись > Добавляем название и IP адрес терминала.
- Включаем *может принимать уведомления от системы*.
- Тип TTS: *majordroid*.
- Включаем *может проигрывать медиа-контент*.
- Тип плеера: *MajorDroid*.
- Сохраняем.

Также можно выбрать плеер *MPD* и порт *6600*, тогда MajorDoMo будет управлять mpd напрямую.

**MDM VoiceAssistant**:
- Заходим в Панель управления MajorDomo > Система > Маркет дополнений > Оборудование > MDM VoiceAssistant и устанавливаем модуль.
- Переходим в Устройства > MDM VoiceAssistant.
- Выбираем ранее созданный терминал.
- Выбираем Сервис синтеза речи

  Если есть API ключ от Яндекса, лучше выбрать Yandex TTS, ~~если нет то Google~~ Yandex может работать с пустым ключом (пока).
- Чувствительность реагирования на ключевое слово

  Чем больше тем лучше слышит, но будет много ложных срабатываний.
- Сервис распознавания речи

  Можно выбрать wit.ai или Microsoft, но для них нужно получить API ключ. Google работает без ключа.
- Сохраняем.
## Запись ключевых слов
**Важно!** Для компиляции нужно [запустить локальный сервис или использовать универсальные модели](https://github.com/Aculeasis/mdmTerminal2/wiki/snowboy)

- Переходим в Устройства >  MDM VoiceAssistant > Выбираем наш терминал > Запись ключевого слова.
- В самом верху выбираем какую модель-активатор мы хотим создать. Если модель уже существует, она будет перезаписана. Можно создать до 6 фраз-активаторов.
- Нажимаем **Запись**, последовательно записываем 3 образца голоса.
- (Опционально) Прослушиваем записи.
- Нажимаем **Компиляция**. Терминал отправит образцы на сервер snowboy и получит готовую модель.

  Если все прошло хорошо, терминал выполнит реинициализацию моделей и начнет активироваться по новой фразе.

Модели хранятся в `mdmTerminal2/src/resources/models/` и имеют расширение `.pmdl`. Они идентичны моделям в **mdmPiTerminal**. Если вы хотите убрать фразу из активации вам нужно удалить соответствующую модель.

# Системные требования
- Python 3.5 +
- Snowboy:
  - OS: Linux (рекомендую debian-based)
  - Architectures: armv7l, aarch64, x86_64
- [Porcupine](https://github.com/Aculeasis/mdmTerminal2/wiki/porcupine): Linux, [Windows](https://github.com/Aculeasis/mdmTerminal2/wiki/windows), Raspberry Pi, Armlinux (a9-neon).

# Решение проблем
- Если после установки возникают ошибки со snowboy - [соберите его вручную](https://github.com/Aculeasis/mdmTerminal2/wiki/snowboy#%D0%A1%D0%B1%D0%BE%D1%80%D0%BA%D0%B0-snowboy-_snowboydetectso).
- Если не работает USB микрофон, попробуйте выдернуть и вставить обратно, иногда это помогает.
- Заикание rhvoice* в конце фраз лечится использованием одного из конфигов для `asound.conf`. Или отключением кэша (wav не заикается)
- Если голос терминала искажается при активации, нужно настраивать `asound.conf` или попробовать другие конфиги.
- Если терминал плохо распознает голос т.к. записывает сам себя, `blocking_listener = 1` может помочь.
- Ошибка во время компиляции модели `Hotword is too long` возникает из-за того что в семпл попало слишком много
аудиоданных. Прослушайте соответствующие семплы, перепишите их и попробуйте снова.

# Сообщество
- [Обсуждение на форуме MajorDoMo](https://mjdm.ru/forum/viewtopic.php?f=5&t=5460)
- [Группа в Telegram](https://t.me/mdmPiTerminal)

# Ссылки
- [mdmPiTerminal](https://github.com/devoff/mdmPiTerminal)
- [В докере](https://github.com/Aculeasis/mdmt2-docker)
- [MDM VoiceAssistant](https://github.com/lanket/mdmPiTerminalModule)
- [MajorDoMo](https://github.com/sergejey/majordomo)
- [Snowboy](https://github.com/Kitt-AI/snowboy)
- [Porcupine](https://github.com/Picovoice/Porcupine)
- [rhvoice-rest](https://github.com/Aculeasis/rhvoice-rest)
- [pocketsphinx-rest](https://github.com/Aculeasis/pocketsphinx-rest)
