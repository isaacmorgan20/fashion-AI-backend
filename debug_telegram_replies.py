import asyncio
from app.firebase import initialize_firebase, get_firestore_client
from app.routes import get_user_channel, _send_channel_reply
from unittest.mock import AsyncMock, patch
from app.telegram import telegram_service

async def test_reply_routing():
    initialize_firebase()
    db = get_firestore_client()
    
    print('Testing reply routing for both sellers...')
    print()
    
    # Get channels for both sellers
    channel1 = get_user_channel(db, 'BvZM8wp75LTVBWUZeJnt3sj1oIu1', 'telegram')
    channel2 = get_user_channel(db, 'sl36LXumSKafrZIW357HBj27iXo2', 'telegram')
    
    token1 = channel1.get('credentials', {}).get('bot_token')
    token2 = channel2.get('credentials', {}).get('bot_token')
    
    print('Seller 1 bot token:', token1[:20] + '...' if token1 else 'MISSING')
    print('Seller 2 bot token:', token2[:20] + '...' if token2 else 'MISSING')
    print()
    
    # Test 1: Reply from Seller 1
    print('Test 1: Human agent replies in Seller 1 conversation...')
    with patch.object(telegram_service, 'send_text_message', new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {'ok': True, 'result': {'message_id': 999}}
        
        await _send_channel_reply(
            seller_id='BvZM8wp75LTVBWUZeJnt3sj1oIu1',
            to_identifier='1175028174',
            message='Hello from Seller 1 human agent!',
            channel=channel1
        )
        
        mock_send.assert_called_once()
        called_args = mock_send.call_args
        used_token = called_args[0][0]
        chat_id = called_args[0][1]
        text = called_args[0][2]
        
        print('  Used bot token:', used_token[:20] + '...')
        print('  Chat ID:', chat_id)
        print('  Message:', text)
        print('  Correct token:', 'YES' if used_token == token1 else 'NO')
        print('  Match Seller 1:', used_token == token1)
        print()
    
    # Test 2: Reply from Seller 2
    print('Test 2: Human agent replies in Seller 2 conversation...')
    with patch.object(telegram_service, 'send_text_message', new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {'ok': True, 'result': {'message_id': 999}}
        
        await _send_channel_reply(
            seller_id='sl36LXumSKafrZIW357HBj27iXo2',
            to_identifier='7480486807',
            message='Hello from Seller 2 human agent!',
            channel=channel2
        )
        
        mock_send.assert_called_once()
        called_args = mock_send.call_args
        used_token = called_args[0][0]
        chat_id = called_args[0][1]
        text = called_args[0][2]
        
        print('  Used bot token:', used_token[:20] + '...')
        print('  Chat ID:', chat_id)
        print('  Message:', text)
        print('  Correct token:', 'YES' if used_token == token2 else 'NO')
        print('  Match Seller 2:', used_token == token2)
        print()
    
    # Verify tokens are different
    print('Token isolation check:')
    print('  Seller 1 token == Seller 2 token:', token1 == token2)
    print('  Tokens are different:', token1 != token2)

if __name__ == '__main__':
    asyncio.run(test_reply_routing())