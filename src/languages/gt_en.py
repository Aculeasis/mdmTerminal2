# Generated by scripts/localization_gen.py

LANG_CODE = {
    'IETF': 'en-US',
    'ISO': 'en',
    'aws': 'en-US',
}

YANDEX_EMOTION = {
    'good': 'good',
    'neutral': 'neutral',
    'evil': 'evil',
}

YANDEX_SPEAKER = {
    'jane': 'Jane',
    'oksana': 'Oksana',
    'alyss': 'Alyss',
    'omazh': 'Omazh',
    'zahar': 'Zahar',
    'ermil': 'Ermil',
}

RHVOICE_SPEAKER = {
    'alan': 'Alan',
    'bdl': 'bdl',
    'clb': 'clb',
    'slt': 'slt',
    'anna': 'Anna',
}

AWS_SPEAKER = {
    'Joey': 'Joey',
    'Justin': 'Justin',
    'Matthew': 'Matthew',
    'Ivy': 'Ivy',
    'Joanna': 'Joanna',
    'Kendra': 'Kendra',
    'Kimberly': 'Kimberly',
    'Salli': 'Salli',
}

_LNG = {  # google translate - it's a good idea!
    # config.py#L93
    'Ошибка получения ключа для Yandex: {}': 'Error receiving key for Yandex: {}',
    # config.py#L307
    'Ошибка сохранения {}: {}': 'Error saving {}: {}',
    # config.py#L314
    'Файл не найден: {}': 'File not found: {}',
    # config.py#L319
    'Ошибка загрузки {}: {}': 'Loading error {}: {}',
    # config.py#L348
    'Конфигурация сохранена за {}': 'Configuration saved for {}',
    # config.py#L349
    'Конфигурация сохранена!': 'Configuration saved!',
    # config.py#L354
    'Директория с моделями не найдена {}': 'Model directory not found {}',
    # config.py#L368
    'Загружено {} моделей': 'Uploaded {} models',
    # config.py#L376
    'Файл настроек не найден по пути {}. Для первого запуска это нормально': 'Settings file not found on path {}. This is normal for the first run.',
    # config.py#L382
    'Загружено {} опций за {}': 'Uploaded {} options for {}',
    # config.py#L383
    'Конфигурация загружена!': 'Configuration uploaded!',
    # config.py#L390
    'Ошибка инициализации языка {}: {}': 'Error initializing language {}: {}',
    # config.py#L391
    'Локализация {} загружена за {}': 'Localization {} loaded for {}',
    # config.py#L409
    'Конфигурация изменилась': 'Configuration changed',
    # config.py#L412
    'Конфигурация не изменилась': 'The configuration has not changed',
    # config.py#L428
    'Директория c tts кэшем не найдена {}': 'Directory with tts cache not found {}',
    # config.py#L451
    'Удалены поврежденные файлы: {}': 'Corrupted files deleted: {}',
    # config.py#L454
    'Размер tts кэша {}: {}': 'Size of tts cache {}: {}',
    'Ок.': 'OK.',
    'Удаляем...': 'Delete ...',
    # config.py#L473
    'Удалено: {}': 'Deleted: {}',
    # config.py#L474
    'Удалено {} файлов. Новый размер TTS кэша {}': 'Deleted {} files. New TTS cache size {}',
    # config.py#L480
    'Директория {} не найдена. Создаю...': 'Directory {} not found. I create ...',
    # config.py#L485 terminal.py#L311 player.py#L174
    'Файл {} не найден.': 'File {} not found.',
    # config.py#L485
    'Это надо исправить!': 'This must be fixed!',
    # config.py#L497
    'Терминал еще не настроен, мой IP адрес: {}': 'The terminal is not configured yet, my IP address is {}',
    # loader.py#L67
    'Приветствую. Голосовой терминал настраивается, три... два... один...': 'Greetings. The voice terminal is configured, three ... two ... one ...',
    # loader.py#L95
    'Голосовой терминал завершает свою работу.': 'The voice terminal is shutting down.',
    # listener.py#L93
    '{} слушает': '{} listening',
    # listener.py#L94;#L105
    'Голосовая активация по {}{}': 'Voice Activated by {} {}',
    # modules.py#L21;#L24;#L18
    'блокировка': 'blocking',
    # modules.py#L22
    'Блокировка снята': 'The lock is released',
    # modules.py#L26
    'Блокировка включена': 'Lock On',
    # modules.py#L17
    'Блокировка': 'Lock',
    'Включение/выключение блокировки терминала': 'Turn on / off terminal lock',
    # modules.py#L34;#L31
    'выход': 'exit',
    # modules.py#L35
    'Внимание! Выход из режима разработчика': 'Attention! Exit Developer Mode',
    # modules.py#L36;#L30
    'режим разработчика': 'developer mode',
    # modules.py#L38
    "Внимание! Включён режим разработчика. Для возврата в обычный режим скажите 'выход'": "Attention! Developer mode is on. To return to normal mode, say 'exit'",
    # modules.py#L29 modules_manager.py#L24
    'Отладка': 'Debugging',
    # modules.py#L29
    'Режим настройки и отладки': 'Setup and Debug Mode',
    # modules.py#L48
    'Модуль {} не найден': 'Module {} not found',
    # modules.py#L52
    'Модуль {} системный, его нельзя настраивать': 'The module {} is system, it cannot be configured',
    # modules.py#L54;#L43
    'активировать': 'activate',
    'деактивировать': 'deactivate',
    'активировать везде': 'activate everywhere',
    # modules.py#L55;#L43
    'удалить': 'remove',
    'восстановить': 'reestablish',
    # modules.py#L58
    'Модуль {} удален. Вначале его нужно восстановить': 'The module {} has been removed. It must first be restored.',
    # modules.py#L61
    'Модуль {} уже в режиме {}': 'Module {} is already in {} mode',
    # modules.py#L62
    'Теперь модуль {} доступен в режиме {}': 'The {} module is now available in {} mode',
    # modules.py#L67
    'Модуль {} и так {}': 'Module {} and so {}',
    # modules.py#L68
    'Модуль {} {}': 'Module {} {}',
    # modules.py#L71
    'Это невозможно, откуда тут {}': 'It’s impossible, where is it from {}',
    # modules.py#L42
    'Менеджер': 'Manager',
    'Управление модулями': 'Module management',
    # modules.py#L75;#L76
    'Скажи': 'Tell me',
    # modules.py#L75
    'Произнесение фразы': 'Pronouncing Phrases',
    # modules.py#L81;#L82
    'Ничего': 'Nothing',
    # modules.py#L94;#L100
    'до': 'before',
    # modules.py#L100
    'от': 'from',
    # modules.py#L109
    'Это слишком много для меня - считать {} чисел.': "It's too much for me to count {} numbers.",
    # modules.py#L127
    'Я всё сосчитала': 'I counted everything',
    # modules.py#L88
    'считалка': 'reading room',
    'Считалка до числа. Или от числа до числа. Считалка произносит не больше 20 чисел за раз': 'Count to number. Or from number to number. The reader says no more than 20 numbers at a time',
    # modules.py#L89
    'сосчитай': 'count',
    'считай': 'count',
    'посчитай': 'count',
    # modules.py#L135;#L143;#L190;#L204
    'Ошибка': 'Error',
    # modules.py#L139;#L152
    'Не поддерживается для {}': 'Not supported for {}',
    # modules.py#L142
    ' Я очень {}.': ' I am very {}.',
    # modules.py#L143
    'Меня зовут {}.{}': 'My name is {}.{}',
    # modules.py#L131
    'Кто я': 'Who am I',
    'Получение информации о настройках голосового генератора (только для Яндекса и RHVoice)': 'Getting information about the settings of the voice generator (only for Yandex and RHVoice)',
    # modules.py#L132
    'кто ты': 'Who are you',
    'какая ты': 'what are you',
    # modules.py#L146
    'Теперь я': 'Now I',
    'Изменение характера или голоса голосового генератора (только для Яндекса и RHVoice)': 'Change the character or voice of a voice generator (Yandex and RHVoice only)',
    # modules.py#L147
    'теперь ты': 'now you',
    'стань': 'become',
    # modules.py#L183;#L197
    'Я уже {}.': "I'm already {}.",
    # modules.py#L187
    'Теперь меня зовут {}, а еще я {}.': 'Now my name is {}, and I am {}.',
    # modules.py#L191
    'без характера': 'without character',
    # modules.py#L201
    'Теперь я очень {} {}.': 'Now I am very {} {}.',
    # modules.py#L212
    'о': 'about',
    'про': 'about',
    'в': 'in',
    # modules.py#L220
    'Ищу в вики о {}': 'I look in the wiki about {}',
    # modules.py#L225
    'Уточните свой вопрос: {}': 'Specify your question: {}',
    # modules.py#L227
    'Я ничего не знаю о {}.': "I don't know anything about {}.",
    # modules.py#L208
    'Вики': 'Wiki',
    'Поиск в Википедии': 'Wikipedia Search',
    # modules.py#L209
    'расскажи': 'tell me',
    'что ты знаешь': 'what do you know',
    'кто такой': 'who it',
    'что такое': 'what',
    'зачем нужен': 'why do i need',
    'для чего': 'for what',
    # modules.py#L237
    'любую фразу': 'any phrase',
    # modules.py#L242
    '. Модуль удален': '. Module removed',
    # modules.py#L243
    'Модуль {} доступен в режиме {}. Для активации скажите {}. Модуль предоставляет {} {}': 'The {} module is available in {} mode. To activate, say {}. The module provides {} {}',
    # modules.py#L250;#L261
    'Всего {} модулей удалены, это: {}': 'Total {} modules removed, this: {}',
    # modules.py#L255
    'Скажите {}. Это активирует {}. Модуль предоставляет {}': 'Say {}. This will activate {}. The module provides {}',
    # modules.py#L262
    'Работа модуля помощь завершена.': 'Help module operation completed.',
    # modules.py#L230
    'Помощь': 'Help',
    'Справку по модулям (вот эту)': 'Module Help (this one)',
    # modules.py#L231
    'помощь': 'help',
    'справка': 'reference',
    'help': 'help',
    'хелп': 'help',
    # modules.py#L269
    'Come Along With Me.': 'Come Along With Me.',
    # modules.py#L266
    'Выход': 'Exit',
    'Завершение работы голосового терминала': 'Voice terminal shutdown',
    # modules.py#L267
    'завершение работы': 'completion of work',
    'завершить работу': 'to finish work',
    'завершить': 'to complete',
    # modules.py#L275
    'Терминал перезагрузится через 5... 4... 3... 2... 1...': 'The terminal will reboot in 5 ... 4 ... 3 ... 2 ... 1 ...',
    # modules.py#L272;#L273
    'Перезагрузка': 'Reboot',
    # modules.py#L272
    'Перезапуск голосового терминала': 'Voice terminal restart',
    # modules.py#L273
    'Ребут': 'Reboot',
    'Рестарт': 'Restart',
    'reboot': 'reboot',
    # modules.py#L286;#L278;#L279
    'громкость': 'volume',
    # modules.py#L278
    'Изменение громкости': 'Volume change',
    # modules.py#L279
    'громкость музыки': 'music volume',
    # modules.py#L296 modules_manager.py#L363
    'Вы ничего не сказали?': 'You didn’t say anything?',
    # modules.py#L300
    'IP сервера не задан.': 'Server IP is not set.',
    # modules.py#L301
    'IP сервера не задан, исправьте это! Мой IP адрес: {}': 'Server IP is not set, fix it! My IP Address: {}',
    # modules.py#L304
    'Скажи ': 'Tell me ',
    # modules.py#L310
    'Запрос был успешен: {}': 'The request was successful: {}',
    # modules.py#L313;#L314
    'Ошибка коммуникации с сервером: {}': 'Error communicating with server: {}',
    # modules.py#L292
    'Мажордом': 'Majordom',
    'Отправку команд на сервер': 'Sending commands to the server',
    # modules.py#L320
    'Соответствие фразе не найдено: {}': 'No matching phrase found: {}',
    # modules.py#L317
    'Терминатор': 'Terminator',
    'Информацию что соответствие фразе не найдено': 'Information that no matching phrase was found',
    # modules_manager.py#L24
    'Обычный': 'Normal',
    'Любой': 'Any',
    # modules_manager.py#L29
    'восстановлен': 'restored',
    'удален': 'deleted',
    # modules_manager.py#L191
    'Отключенные модули: {}': 'Disabled modules: {}',
    # modules_manager.py#L193
    'Неактивные модули: {}': 'Inactive modules: {}',
    # modules_manager.py#L195
    'Активные модули: {}': 'Active Modules: {}',
    # modules_manager.py#L209
    'Обнаружены конфликты в режиме {}: {}': 'Conflicts detected in {} mode: {}',
    # modules_manager.py#L444
    'Захвачено {}': 'Captured {}',
    # terminal.py#L161
    'Пустая очередь? Impossible!': 'An empty queue? Impossible!',
    # terminal.py#L165
    'Получено {}:{}, lvl={} опоздание {} секунд.': 'Received {}: {}, lvl = {} delay {} seconds.',
    # terminal.py#L167
    '{} Игнорирую.': '{} Ignore it.',
    # terminal.py#L183
    'Не верный вызов, WTF? {}:{}, lvl={}': 'Wrong call, WTF? {}: {}, lvl = {}',
    # terminal.py#L195;#L197;#L219
    'Недопустимое значение: {}': 'Invalid value: {}',
    # terminal.py#L204;#L206
    'Не настроено': 'Not configured',
    # terminal.py#L208;#L210
    'Громкость {} процентов': 'Volume {} percent',
    # terminal.py#L226;#L228
    'Громкость музыки {} процентов': 'Music volume {} percent',
    # terminal.py#L282
    'первого': 'the first',
    'второго': 'second',
    'третьего': 'third',
    # terminal.py#L284;#L285
    'Ошибка записи - недопустимый параметр': 'Write Error - Invalid Parameter',
    # terminal.py#L292
    'Запись {} образца на 5 секунд начнется после звукового сигнала': 'Recording {} of the sample for 5 seconds will start after a beep',
    # terminal.py#L297
    'Запись {} образца завершена. Вы можете прослушать свою запись.': 'Recording {} of the sample is completed. You can listen to your recording.',
    # terminal.py#L301
    'Ошибка сохранения образца {}: {}': 'Error saving sample {}: {}',
    # terminal.py#L310
    'Ошибка воспроизведения - файл {} не найден': 'Playback Error - File {} Not Found',
    # terminal.py#L318;#L319
    'Ошибка компиляции - файл {} не найден.': 'Compilation error - file {} was not found.',
    # terminal.py#L339
    'Ошибка удаление модели номер {}': 'Error deleting model number {}',
    # terminal.py#L344
    'Модель номер {} удалена': 'Model number {} deleted',
    # terminal.py#L348
    'Модель номер {} не найдена': 'Model number {} not found',
    # terminal.py#L498
    'Полный консенсус по модели {} не достигнут [{}/{}]. Советую пересоздать модель.': 'Full consensus on model {} not reached [{} / {}]. I advise you to recreate the model.',
    # terminal.py#L502
    'Полный консенсус по модели {} не достигнут. Компиляция отменена.': 'Full consensus on model {} has not been reached. Compilation canceled.',
    # terminal.py#L509
    'Компилирую {}': 'Compiling {}',
    # terminal.py#L514
    'Ошибка компиляции модели {}: {}': 'Error compiling model {}: {}',
    # terminal.py#L515
    'Ошибка компиляции модели номер {}': 'Error compiling model number {}',
    # terminal.py#L521
    'Модель{} скомпилирована успешно за {}: {}': 'Model {} compiled successfully for {}: {}',
    # terminal.py#L522
    'Модель{} номер {} скомпилирована успешно за {}': 'Model {} number {} compiled successfully for {}',
    # logger.py#L148
    'Логгирование в {} невозможно - отсутствуют права на запись. Исправьте это': 'Logging in {} is not possible - there are no write permissions. Fix it',
    # stts.py#L65
    'Неизвестный провайдер: {}': 'Unknown provider: {}',
    # stts.py#L68
    '{} за {}{}: {}': '{} behind {}{}: {}',
    # stts.py#L86
    '{}найдено в кэше': '{} found in cache',
    # stts.py#L97
    '{}сгенерированно {}': '{} generated {}',
    # stts.py#L177
    "Ошибка синтеза речи от {}, ключ '{}'. ({})": "Speech synthesis error from {}, key '{}'. ({})",
    # stts.py#L231;#L257;#L354;#L355
    'Микрофоны не найдены': 'No microphones found',
    # stts.py#L255
    'Доступны {}, от 0 до {}.': 'Available are {}, from 0 to {}.',
    # stts.py#L258
    'Не верный индекс микрофона {}. {}': 'Invalid microphone index {}. {}',
    # stts.py#L281
    'Голос записан за {}': 'Voice recorded for {}',
    # stts.py#L383
    'Во время записи произошел сбой, это нужно исправить': 'There was a failure while recording, it needs to be fixed',
    # stts.py#L409;#L410
    'Ошибка распознавания - неизвестный провайдер {}': 'Recognition Error - Unknown Provider {}',
    # stts.py#L412
    'Для распознавания используем {}': 'For recognition we use {}',
    # stts.py#L429
    'Произошла ошибка распознавания': 'Recognition Error Occurred',
    # stts.py#L431
    "Ошибка распознавания речи от {}, ключ '{}'. ({})": "Speech recognition error from {}, key '{}'. ({})",
    # stts.py#L436
    'Распознано за {}': 'Recognized for {}',
    # stts.py#L456
    'Распознано: {}. Консенсус: {}': 'Recognized: {}. Consensus: {}',
    # stts.py#L543
    'Привет': 'Hi',
    'Слушаю': "I'm listening",
    'На связи': 'In touch',
    'Привет-Привет': 'Hi Hi',
    # stts.py#L544
    'Я ничего не услышала': "I didn't hear anything",
    'Вы ничего не сказали': "You didn't say anything",
    'Ничего не слышно': 'Can not hear anything',
    'Не поняла': 'I did not get that',
    # stts.py#L545
    'Ничего не слышно, повторите ваш запрос': 'Hearing nothing, repeat your request',
    # player.py#L176
    'Неизвестный тип файла: {}': 'Unknown file type: {}',
    # player.py#L177
    'Играю {} ...': "I'm playing {} ...",
    'Стримлю {} ...': 'Streaming {} ...',
    # updater.py#L54;#L177
    'Выполнен откат.': 'Rollback completed.',
    # updater.py#L111;#L112
    'Во время обновления возникла ошибка': 'An error occurred while updating',
    # updater.py#L122;#L123
    'Вы используете последнюю версию терминала.': 'You are using the latest version of the terminal.',
    # updater.py#L126
    'Файлы обновлены: {}': 'Files updated: {}',
    # updater.py#L140;#L144;#L146
    'Терминал успешно обновлен.': 'The terminal has been updated successfully.',
    # updater.py#L146
    'Требуется перезапуск.': 'Restart required.',
    # updater.py#L158
    'Во время обработки обновления или установки зависимостей возникла ошибка': 'An error occurred while processing the update or installing dependencies',
    # updater.py#L165
    'Выполняется откат обновления.': 'Updates are rolled back.',
    # updater.py#L172
    'Во время отката обновления возникла ошибка: {}': 'An error occurred while rolling back the update: {}',
    # updater.py#L173
    'Откат невозможен.': 'Rollback is not possible.',
    # updater.py#L176
    'Откат обновления выполнен успешно.': 'The rollback of the update was successful.',
    # updater.py#L183
    'Зависимости {} {}обновлены: {}': 'Dependencies {} {} updated: {}',
    'не ': 'not ',
    # music_controls.py#L88 lib/base_music_controller.py#L144
    'Ошибка подключения к {}-серверу': 'Error connecting to {} server',
    # server.py#L39
    'Ошибка запуска сервера{}.': 'Error starting server {}.',
    ' - адрес уже используется': ' - the address is already in use',
    # server.py#L40
    'Ошибка запуска сервера на {}:{}: {}': 'Error starting server on {}: {}: {}',
}
