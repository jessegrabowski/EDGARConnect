def progress_bar(current, total, mean_time, verb):
    remaining = mean_time * (total - current)
    minutes, seconds = np.divmod(remaining, 60)
    minutes = int(minutes)
    minutes = '0' * (2 - len(str(minutes))) + str(minutes)
    seconds = int(seconds)
    seconds = '0' * (2 - len(str(seconds))) + str(seconds)
    
    pct_complete = int(current / total * 50)
    bar = f'{verb} [' + '=' * pct_complete + ' ' * (50 - pct_complete) + ']'
    
    print(bar, f'ETA: {minutes}:{seconds}', end='\r')
